import type { EndpointResponse, ExternalTopologyResponse, ValidationReportResponse } from '@/client/types.gen';

export type RecoveryProgress =
  | 'validation_pending'
  | 'validation_passed'
  | 'activation_pending'
  | 'binding_update_pending'
  | 'topology_refresh_pending';

type ApiResult<T> = { data?: T; error?: unknown };
type EndpointOptions = { path: { endpoint_uuid: string }; signal?: AbortSignal };

type RecoveryDependencies = {
  endpointUuid: string;
  validate: (options: EndpointOptions) => Promise<ApiResult<unknown>>;
  getEndpoint: (options: EndpointOptions) => Promise<ApiResult<EndpointResponse>>;
  listReports: (options: EndpointOptions) => Promise<ApiResult<ValidationReportResponse[]>>;
  activate: (options: EndpointOptions) => Promise<ApiResult<unknown>>;
  updateBinding: (signal?: AbortSignal) => Promise<ApiResult<ExternalTopologyResponse>>;
  normalizeError: (error: unknown, fallback: string) => string;
  onProgress?: (progress: RecoveryProgress) => void;
  signal?: AbortSignal;
  pollIntervalMs?: number;
  timeoutMs?: number;
};

const PASSING_REPORT_STATUSES = new Set(['passed', 'live_voice_eligible']);
const ACTIVATABLE_STATUSES = new Set(['validation_only', 'degraded']);

function resultData<T>(result: ApiResult<T>, normalizeError: RecoveryDependencies['normalizeError'], fallback: string): T {
  if (result.error) throw new Error(normalizeError(result.error, fallback));
  if (!result.data) throw new Error(fallback);
  return result.data;
}

const endpointOptions = (endpointUuid: string, signal?: AbortSignal): EndpointOptions => ({
  path: { endpoint_uuid: endpointUuid },
  signal,
});

function throwIfAborted(signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException('Topology recovery cancelled', 'AbortError');
}

function wait(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Topology recovery cancelled', 'AbortError'));
      return;
    }
    const timer = window.setTimeout(resolve, ms);
    signal?.addEventListener('abort', () => {
      window.clearTimeout(timer);
      reject(new DOMException('Topology recovery cancelled', 'AbortError'));
    }, { once: true });
  });
}

/** Runs the single-confirmation validation → activation → draft binding update chain. */
export async function runTopologyRecovery({
  endpointUuid,
  validate,
  getEndpoint,
  listReports,
  activate,
  updateBinding,
  normalizeError,
  onProgress,
  signal,
  pollIntervalMs = 2_000,
  timeoutMs = 60_000,
}: RecoveryDependencies): Promise<ExternalTopologyResponse> {
  throwIfAborted(signal);
  onProgress?.('validation_pending');
  const validation = await validate(endpointOptions(endpointUuid, signal));
  throwIfAborted(signal);
  if (validation.error) throw new Error(normalizeError(validation.error, 'Failed to request endpoint validation'));

  const deadline = Date.now() + timeoutMs;
  let endpoint: EndpointResponse;
  while (true) {
    throwIfAborted(signal);
    if (Date.now() >= deadline) throw new Error('Endpoint validation timed out after 60 seconds. Check the endpoint and try again.');
    endpoint = resultData(
      await getEndpoint(endpointOptions(endpointUuid, signal)),
      normalizeError,
      'Failed to check endpoint validation status',
    );
    throwIfAborted(signal);
    if (endpoint.lifecycle_status !== 'pending_validation') break;
    if (Date.now() >= deadline) throw new Error('Endpoint validation timed out after 60 seconds. Check the endpoint and try again.');
    await wait(Math.min(pollIntervalMs, Math.max(0, deadline - Date.now())), signal);
  }

  if (!endpoint.current_validation_report_uuid || !endpoint.current_capability_snapshot) {
    throw new Error('Endpoint validation completed without current evidence. Review the endpoint validation report and try again.');
  }
  const reports = resultData(
    await listReports(endpointOptions(endpointUuid, signal)),
    normalizeError,
    'Failed to read endpoint validation results',
  );
  throwIfAborted(signal);
  const report = reports.find((item) => item.report_uuid === endpoint.current_validation_report_uuid);
  if (!report || !PASSING_REPORT_STATUSES.has(report.status)) {
    throw new Error('Endpoint validation failed. Review the endpoint contract, credentials, and network access before retrying.');
  }
  onProgress?.('validation_passed');

  if (endpoint.lifecycle_status !== 'active') {
    if (!ACTIVATABLE_STATUSES.has(endpoint.lifecycle_status)) {
      throw new Error('Endpoint validation passed, but its lifecycle does not allow activation. Open LangGraph Endpoints to resolve its status.');
    }
    onProgress?.('activation_pending');
    const activation = await activate(endpointOptions(endpointUuid, signal));
    throwIfAborted(signal);
    if (activation.error) throw new Error(normalizeError(activation.error, 'Failed to activate validated endpoint evidence'));
  }

  throwIfAborted(signal);
  onProgress?.('binding_update_pending');
  const updated = await updateBinding(signal);
  throwIfAborted(signal);
  return resultData(updated, normalizeError, 'Failed to update the draft endpoint binding');
}
