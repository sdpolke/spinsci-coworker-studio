/**
 * Pure deploy-pipeline logic for the SpinSci EC2 Deploy_Pipeline.
 *
 * These functions are the testable core the GitHub Actions workflow
 * (`.github/workflows/deploy-ec2.yml`) invokes. They are deliberately PURE:
 * no process spawning, no real network, no clock — all effects (HTTP fetch,
 * time, sleeping) are injected so the property tests (tasks 10.2–10.6) can
 * drive them deterministically, and so the exact code under test is the code
 * that runs in CI.
 *
 * Responsibilities map to the design's "Deploy-logic invariants":
 *  - {@link resolveTargetVersion}  — tag → TARGET_VERSION identity (Property 7)
 *  - {@link deriveImageTag}        — the spinsci-/v prefix stripping the build
 *                                    pipeline and update_remote.sh both use
 *  - {@link checkImageAvailable}   — image-availability gate (Property 8)
 *  - {@link buildSsmParameters}    — SSM AWS-RunShellScript parameter shape
 *  - {@link isHealthy}             — health predicate (Property 12)
 *  - {@link pollHealth}            — health poller (Property 13)
 *  - {@link resolveHealthTimeout}  — timeout bounds + default (Property 14)
 */

/** The deploy dir on the mounted Data_Volume (matches user-data.ts DEPLOY_DIR). */
export const DEPLOY_DIR = '/mnt/spinsci-data/spinsci';

/** The Docker Hub namespace the Build_Pipeline publishes images under. */
export const DOCKERHUB_NAMESPACE = 'spinsciai';

/** The two images a release publishes; both must exist for the gate to pass. */
export const IMAGE_NAMES = ['spinsci-api', 'spinsci-ui'] as const;

/** Health-check timeout bounds and default, in seconds (Req 9.3). */
export const HEALTH_TIMEOUT_MIN_S = 30;
export const HEALTH_TIMEOUT_MAX_S = 600;
export const HEALTH_TIMEOUT_DEFAULT_S = 120;

/** Health-poll interval, fixed within the [5, 30]s band the spec allows (Req 9.1). */
export const HEALTH_POLL_INTERVAL_S = 10;

/**
 * Resolve the Release_Tag the operator/release selected into the exact
 * `TARGET_VERSION` passed to `update_remote.sh`. This is the IDENTITY function:
 * whatever tag comes in (older tag, `latest`, a full `spinsci-v…` tag) is passed
 * through unchanged — the pipeline never substitutes a different tag. The host
 * script does its own resolution; the pipeline must not second-guess it.
 * (Req 4.2, 8.1, 8.2 / Property 7)
 *
 * @throws if the tag is empty/blank — a deploy with no target is a bug, not a default.
 */
export function resolveTargetVersion(tag: string): string {
  const trimmed = (tag ?? '').trim();
  if (trimmed.length === 0) {
    throw new Error(
      'No Release_Tag supplied: a deploy must name an explicit tag; the ' +
        'pipeline never substitutes a default or "latest".',
    );
  }
  return trimmed;
}

/**
 * Derive the Docker Hub image tag from a Release_Tag, mirroring EXACTLY what
 * `.github/workflows/docker-image.yml` and `update_remote.sh` do: strip a
 * leading `spinsci-` then a leading `v`. So `spinsci-v1.28.0` → `1.28.0`,
 * `v1.28.0` → `1.28.0`, `1.28.0` → `1.28.0`. Keeping this identical to the
 * build side is what makes the availability gate meaningful.
 */
export function deriveImageTag(releaseTag: string): string {
  let tag = resolveTargetVersion(releaseTag);
  if (tag.startsWith('spinsci-')) tag = tag.slice('spinsci-'.length);
  if (tag.startsWith('v')) tag = tag.slice('v'.length);
  return tag;
}

/** Minimal response shape the image/health checks need from an HTTP call. */
export interface HttpLike {
  readonly ok: boolean;
  readonly status: number;
  /** Parse the body as JSON; may reject for non-JSON bodies. */
  json(): Promise<unknown>;
}

/** Injectable fetch: returns an HttpLike, or throws on a connection error. */
export type FetchLike = (url: string) => Promise<HttpLike>;

/** Result of the image-availability gate (Property 8). */
export interface ImageGateResult {
  readonly available: boolean;
  /** Human-readable reason, always naming the Release_Tag. */
  readonly reason: string;
  /** The derived image tag that was probed. */
  readonly imageTag: string;
}

/**
 * The Docker Hub tag-existence URL for an image + tag. A `HEAD`/`GET` returning
 * 2xx means the tag is published.
 */
export function dockerHubTagUrl(imageName: string, imageTag: string): string {
  return `https://hub.docker.com/v2/repositories/${DOCKERHUB_NAMESPACE}/${imageName}/tags/${encodeURIComponent(
    imageTag,
  )}/`;
}

/**
 * Gate the deploy on image availability: BOTH `spinsci-api` and `spinsci-ui`
 * must report a published tag before any SSM command is issued. When either is
 * missing the result is `available: false` with a reason naming the Release_Tag,
 * and the caller MUST NOT proceed to OIDC/SSM. (Req 4.5, 8.3 / Property 8)
 *
 * Network/parse errors are treated as "not available" (fail closed) so a flaky
 * registry never lets an unverified tag through.
 */
export async function checkImageAvailable(
  releaseTag: string,
  fetchFn: FetchLike,
): Promise<ImageGateResult> {
  const imageTag = deriveImageTag(releaseTag);

  for (const name of IMAGE_NAMES) {
    let present = false;
    try {
      const res = await fetchFn(dockerHubTagUrl(name, imageTag));
      present = res.ok;
    } catch {
      present = false;
    }
    if (!present) {
      return {
        available: false,
        imageTag,
        reason:
          `Release_Tag "${releaseTag}" is not deployable: image ` +
          `${DOCKERHUB_NAMESPACE}/${name}:${imageTag} is not published on ` +
          'Docker Hub. No SSM command was issued.',
      };
    }
  }

  return {
    available: true,
    imageTag,
    reason: `Release_Tag "${releaseTag}" images are published (tag :${imageTag}).`,
  };
}

/**
 * The `Parameters` block of the SSM `AWS-RunShellScript` command that runs the
 * update on the instance. Runs in the volume-backed deploy dir, exports
 * `TARGET_VERSION` (exactly the selected tag) and `SPINSCI_UPDATE_YES=1` for a
 * non-interactive run, invokes `update_remote.sh` to refresh+pin, then
 * `remote_up.sh` to apply. `SPINSCI_FORCE_OVERWRITE` is never set, so the
 * existing `.env` secrets are preserved. (Req 4.1, 4.2, 7.3, 8.1)
 */
export function buildSsmParameters(releaseTag: string): {
  workingDirectory: string[];
  commands: string[];
} {
  const target = resolveTargetVersion(releaseTag);
  // Single-quote the tag for safe shell embedding (escape embedded quotes).
  const safeTarget = `'${target.replace(/'/g, `'\\''`)}'`;
  return {
    workingDirectory: [DEPLOY_DIR],
    commands: [
      'set -euo pipefail',
      `export TARGET_VERSION=${safeTarget}`,
      'export SPINSCI_UPDATE_YES=1',
      // -E preserves the exported env for the root run.
      'sudo -E ./scripts/update_remote.sh',
      'sudo -E ./remote_up.sh',
    ],
  };
}

/** The outcome of a single health probe, as seen by {@link isHealthy}. */
export interface HealthProbe {
  /** The HTTP response, or undefined when the request threw (unreachable). */
  readonly response?: HttpLike;
  /** The parsed JSON body, if the response was JSON. */
  readonly body?: unknown;
  /** True when the request threw / timed out before any response. */
  readonly errored?: boolean;
}

/**
 * The health predicate (Req 9.2 / Property 12). Healthy IFF the response is a
 * 2xx AND the JSON body reports `status: "ok"` (the shape `/api/v1/health`
 * returns). Any unreachable, timed-out, non-2xx, or non-"ok" response is NOT
 * healthy.
 */
export function isHealthy(probe: HealthProbe): boolean {
  if (probe.errored) return false;
  const res = probe.response;
  if (!res) return false;
  if (!res.ok || res.status < 200 || res.status >= 300) return false;
  const body = probe.body as { status?: unknown } | undefined | null;
  return !!body && typeof body === 'object' && body.status === 'ok';
}

/** Injectable clock (monotonic ms) + sleeper for the poller, so tests fake time. */
export interface Clock {
  /** Current time in ms (monotonic). */
  now(): number;
  /** Resolve after `ms` have "elapsed" on this clock. */
  sleep(ms: number): Promise<void>;
}

/** Result of {@link pollHealth}. */
export interface HealthPollResult {
  readonly healthy: boolean;
  /** Number of probes performed. */
  readonly attempts: number;
}

/**
 * Poll the Health_Endpoint at a fixed interval until it reports healthy or the
 * timeout elapses (Req 9.1, 9.4 / Property 13).
 *
 * Probes at {@link HEALTH_POLL_INTERVAL_S} (within the required [5, 30]s band),
 * returns `{ healthy: true }` on the first healthy probe, and `{ healthy: false }`
 * once `timeoutS` elapses with no healthy probe. Fetch + clock are injected.
 *
 * @param url the health URL (e.g. https://host/api/v1/health)
 * @param timeoutS total timeout in seconds (already resolved via resolveHealthTimeout)
 * @param fetchFn injected fetch
 * @param clock injected clock/sleeper
 * @param intervalS poll interval in seconds (defaults to the fixed interval)
 */
export async function pollHealth(
  url: string,
  timeoutS: number,
  fetchFn: FetchLike,
  clock: Clock,
  intervalS: number = HEALTH_POLL_INTERVAL_S,
): Promise<HealthPollResult> {
  const deadline = clock.now() + timeoutS * 1000;
  const intervalMs = intervalS * 1000;
  let attempts = 0;

  // Always probe at least once, then until the deadline.
  for (;;) {
    attempts += 1;
    const probe = await probeOnce(url, fetchFn);
    if (isHealthy(probe)) {
      return { healthy: true, attempts };
    }
    // Stop if the next sleep would carry us past the deadline.
    if (clock.now() + intervalMs > deadline) {
      return { healthy: false, attempts };
    }
    await clock.sleep(intervalMs);
  }
}

/** Perform one probe, classifying a thrown fetch / bad JSON as errored. */
async function probeOnce(url: string, fetchFn: FetchLike): Promise<HealthProbe> {
  try {
    const response = await fetchFn(url);
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      body = undefined;
    }
    return { response, body };
  } catch {
    return { errored: true };
  }
}

/**
 * Resolve the operator-supplied health-check timeout against the allowed bounds
 * (Req 9.3 / Property 14). Returns the input when within [30, 600]s, the default
 * (120) when unset, and throws a validation error naming the bound when out of
 * range.
 *
 * @param input raw timeout in seconds (string from a workflow input, number, or undefined)
 */
export function resolveHealthTimeout(
  input: string | number | undefined | null,
): number {
  if (input === undefined || input === null || input === '') {
    return HEALTH_TIMEOUT_DEFAULT_S;
  }
  const n = typeof input === 'number' ? input : Number(input);
  if (!Number.isInteger(n) || n < HEALTH_TIMEOUT_MIN_S || n > HEALTH_TIMEOUT_MAX_S) {
    throw new Error(
      `Invalid health-check timeout "${String(input)}": must be an integer ` +
        `within [${HEALTH_TIMEOUT_MIN_S}, ${HEALTH_TIMEOUT_MAX_S}] seconds.`,
    );
  }
  return n;
}
