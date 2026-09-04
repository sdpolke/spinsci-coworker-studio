# Requirements Document

## Introduction

This feature migrates the Dograh voice AI platform from its single-host Docker Compose deployment (`docker-compose.yaml`, driven by `setup_remote.sh` / `remote_up.sh`) to a Kubernetes deployment with KEDA-driven horizontal autoscaling of the API workload.

The business driver is capacity and cost. The target volume is 5000 calls per day concentrated in an 8-to-9-hour business-hours window, with an average handle time of 3 minutes. That yields roughly 29 average concurrent calls and roughly 60 peak-hour concurrent calls. The deployment must provision for 90 concurrent calls with the ability to scale to 120, against a current per-organization default ceiling of 10 (`DEFAULT_ORG_CONCURRENCY_LIMIT` in `api/constants.py`). Because traffic is idle overnight and dense during the business window, replica count must track load rather than sit permanently at peak size.

The runtime model is preserved, not rewritten. Pipecat runs in-process: each call is an asyncio task inside a uvicorn worker (`api/services/pipecat/worker_runner.py`, `api/services/pipecat/run_pipeline.py`), and one process hosts many concurrent call sessions. Horizontal scaling is achieved by adding replicas of the same container image.

Two backend endpoints required by this migration already exist and must be consumed rather than rebuilt:

- `GET /api/v1/health/autoscale-metric` (`api/routes/main.py`) returns fleet-wide active calls plus a warm buffer, read from the `concurrent_calls_fleet` Redis ZSET (`api/services/call_concurrency/rate_limiter.py`). It was written for KEDA and is currently unconsumed.
- `GET /api/v1/health/active-calls` (`api/routes/main.py`) returns the in-flight call count for the individual worker process, written for a Kubernetes `preStop` hook.

The dominant failure mode of this migration is terminating a pod that still holds live calls. uvicorn force-closes call WebSockets on SIGTERM with close code 1012, so every pod-removal path — scale-down, rolling update, node drain — must drain before termination.

Pipecat Cloud migration, a per-call container rewrite, and changes to the per-organization STT/LLM/TTS provider system are out of scope.

## Glossary

- **API_Deployment**: The Kubernetes Deployment running the `spinsci-api` container image serving HTTP, telephony media WebSockets, and WebRTC signaling. Hosts in-process pipecat call sessions.
- **API_Pod**: A single replica of API_Deployment.
- **ARQ_Deployment**: The Kubernetes Deployment running ARQ background workers (`api/tasks/arq.py`), which execute post-call work (webhook delivery, billing, campaign orchestration events) and never host live call pipelines.
- **Singleton_Deployment**: A Kubernetes Deployment restricted to exactly one running replica, used for `ari_manager` and `campaign_orchestrator`.
- **Ingress_Layer**: The Kubernetes ingress controller (or equivalent L7 load balancer) terminating TLS and routing HTTP and WebSocket traffic to API_Deployment, replacing the nginx container in `docker-compose.yaml`.
- **Scaled_Object**: The KEDA `ScaledObject` resource governing the replica count of API_Deployment.
- **Fleet_Metric_Endpoint**: The existing `GET /api/v1/health/autoscale-metric` endpoint in `api/routes/main.py`.
- **Drain_Endpoint**: The existing `GET /api/v1/health/active-calls` endpoint in `api/routes/main.py`, which reports the calling worker process's in-flight call count.
- **PreStop_Handler**: The Kubernetes `lifecycle.preStop` hook on API_Deployment that polls Drain_Endpoint before allowing SIGTERM.
- **Per_Pod_Call_Target**: The number of simultaneous active calls one API_Pod is sized to carry. KEDA divides the Fleet_Metric_Endpoint value by this number to derive desired replicas.
- **Load_Test**: A repeatable test that drives synthetic concurrent calls against a single API_Pod and records CPU, resident memory, and event-loop lag per active call.
- **Turn_Workload**: The Kubernetes workload running coturn, providing TURN/STUN relay for WebRTC over UDP.
- **External_Datastore**: A Postgres, Redis, or object-storage instance managed outside the Kubernetes application manifests (managed cloud service or dedicated instance).
- **Concurrency_Service**: The existing `CallConcurrencyService` in `api/services/call_concurrency/service.py` together with `RateLimiter` in `api/services/call_concurrency/rate_limiter.py`.
- **Deployment_Documentation**: The operator-facing documentation set under `docs/deployment/`, including the existing `docs/deployment/scaling.mdx`.
- **Active_Call**: A call session counted by Concurrency_Service as holding a live concurrency slot.
- **Measured_Sustainable_Concurrency**: The highest concurrency ladder step at which one API_Pod sustains Active_Calls within the event-loop lag thresholds recorded in the Load_Test definition.
- **Deployment_Readiness_Checklist**: A checked-in, operator-completed record of external prerequisites that cannot be verified from inside the cluster, including telephony provider channel and rate capacity.

## Requirements

### Requirement 1: Kubernetes Manifests for the API Workload

**User Story:** As a platform operator, I want the API workload defined as Kubernetes resources, so that I can run more than one host's worth of call capacity without hand-managing Compose stacks.

#### Acceptance Criteria

1. THE API_Deployment SHALL run the same container image and application entrypoint used by the `api` service in `docker-compose.yaml`, and SHALL reference that image by an immutable tag or digest recorded in the manifests rather than a mutable floating tag.
2. IF the `pipecat` git submodule checked out at image build time is not at commit `e2c6a2918254439a28521d85bd049778ede2d4be`, THEN THE image build SHALL fail with a non-zero exit status and an error indicating the expected and actual submodule commit, and SHALL NOT publish an image.
3. THE API_Deployment SHALL declare CPU and memory `requests` and `limits` per API_Pod as explicit literal values in the manifests, where each value is at least the peak CPU and peak resident memory observed in the Requirement 10 Load_Test at Per_Pod_Call_Target concurrent calls plus at least 20 percent headroom, and Deployment_Documentation SHALL record the observed Load_Test peaks used to derive them.
4. THE API_Deployment SHALL expose a Kubernetes Service that routes to the API_Pod HTTP port, and that Service SHALL carry both HTTP request traffic and WebSocket upgrade traffic to the same port.
5. THE API_Deployment SHALL declare a readiness probe issuing `GET /api/v1/health` with an explicit period, timeout, success threshold, and failure threshold recorded in the manifests, where the timeout is at least 1 second and less than the period, and SHALL treat any non-2xx response or timeout as a probe failure that removes the API_Pod from Service endpoints.
6. THE API_Deployment SHALL declare a liveness probe that is a separate probe definition from the readiness probe, with explicit period, timeout, and failure threshold values recorded in the manifests, and whose `period × failureThreshold` product is greater than the maximum drain wait configured on PreStop_Handler, so that an API_Pod holding live calls during drain is never restarted by the liveness probe.
7. THE API_Deployment SHALL set `terminationGracePeriodSeconds` to a value greater than the maximum PreStop_Handler drain wait plus the readiness-removal delay, so that Kubernetes does not force-kill an API_Pod that is still draining live calls.
8. THE API_Deployment SHALL set `FASTAPI_WORKERS` to an explicit literal integer value of 1 or greater in the manifests, and Deployment_Documentation SHALL state that value, the reason for it given that Pipecat call tasks run in-process within each uvicorn worker, and the relationship between that value and Per_Pod_Call_Target.
9. WHERE the deployment runs behind a TLS-terminating proxy, THE API_Deployment SHALL set `FORWARDED_ALLOW_IPS` to the proxy source addresses so that a request arriving over the public `https` origin is reconstructed with the `https` scheme and the public host when telephony webhook signature verification computes the request URL.
10. IF `FORWARDED_ALLOW_IPS` is unset or does not include the proxy source address while the deployment runs behind a TLS-terminating proxy, THEN THE deployment validation SHALL fail with an error indicating that webhook signature verification would receive a non-public request URL.
11. THE Kubernetes manifests SHALL be checked into the repository under a single directory whose path is recorded in Deployment_Documentation, and all manifests in that directory SHALL pass a server-side dry-run validation with zero errors.

### Requirement 2: WebSocket-Aware Ingress and Load Balancing

**User Story:** As a platform operator, I want ingress that tolerates long-lived call connections, so that a 3-minute call is not severed by a proxy timeout.

#### Acceptance Criteria

1. WHEN a request arrives on the public hostname, THE Ingress_Layer SHALL route it to the API_Deployment Service, forwarding the `Upgrade: websocket` and `Connection: Upgrade` headers unmodified for requests that carry them so the connection is established as a WebSocket rather than answered as a plain HTTP request.
2. THE Ingress_Layer SHALL apply idle, read, and send timeouts of at least 3600 seconds to WebSocket routes, and SHALL NOT close a WebSocket connection that has been idle for fewer than 3600 seconds.
3. THE Ingress_Layer SHALL terminate TLS for the public hostname and forward `X-Forwarded-Proto: https` to API_Pods; IF a request arrives on the public hostname over plain HTTP, THEN THE Ingress_Layer SHALL respond with a redirect to the HTTPS equivalent of the same path and query string.
4. WHEN the Ingress_Layer selects a backend for a new connection, THE Ingress_Layer SHALL choose the ready API_Pod with the fewest active connections, such that after distributing N connections across M ready API_Pods the per-pod active connection counts differ by at most 1.
5. WHEN an API_Pod enters a draining state, THE Ingress_Layer SHALL stop routing new connections to that API_Pod within 5 seconds and SHALL keep every already-established connection on that API_Pod open until the client or API_Pod closes it, or until the pod termination grace period expires.
6. THE Ingress_Layer SHALL forward the request path of the telephony media WebSocket route `/api/v1/telephony/ws/...` to API_Pods byte-for-byte, without stripping, rewriting, normalizing, or percent-decoding the trailing capability-token path segment verified by `api/services/telephony/ws_auth.py`.
7. THE Ingress_Layer SHALL forward the request query string to API_Pods unmodified, including the `token` query parameter used by the ARI media WebSocket, so that token verification at connect time sees the value that was minted.
8. IF an upgrade request arrives on a WebSocket route and no ready API_Pod is available, THEN THE Ingress_Layer SHALL refuse the upgrade within 5 seconds with a response indicating the service is temporarily unavailable, and SHALL NOT hold the connection open awaiting a backend.

### Requirement 3: KEDA Autoscaling Driven by the Existing Fleet Metric

**User Story:** As a platform operator, I want replica count to follow live call volume, so that I pay for peak capacity only during the business-hours window.

#### Acceptance Criteria

1. WHEN each polling interval of 15 seconds elapses, THE Scaled_Object SHALL scrape Fleet_Metric_Endpoint (`GET /api/v1/health/autoscale-metric`) with a request timeout of at most 5 seconds and SHALL derive desired API_Deployment replicas from the returned numeric value.
2. THE Scaled_Object SHALL send the devops secret header `X-SpinSci-Devops-Secret` with each scrape, sourced by reference from a Kubernetes Secret, and SHALL NOT carry the secret value inline in the Scaled_Object definition.
3. THE Scaled_Object SHALL compute the desired replica count as the scraped value divided by Per_Pod_Call_Target, rounded up to the next whole replica, then clamped to the configured minimum and maximum replica counts.
4. THE Scaled_Object SHALL pass a warm-buffer value to Fleet_Metric_Endpoint through its `buffer` query parameter as a whole number of calls in the range 0 to 120 inclusive, set equal to Per_Pod_Call_Target so that one pod of headroom stays warm, and Deployment_Documentation SHALL state that value in units of calls.
5. THE Scaled_Object SHALL define a minimum replica count of exactly 1 and a maximum replica count equal to 120 divided by Per_Pod_Call_Target rounded up to the next whole replica.
6. WHEN the scraped value corresponds to 90 simultaneous Active_Calls, THE Scaled_Object SHALL request a replica count R such that R multiplied by Per_Pod_Call_Target is greater than or equal to 90, and R does not exceed the configured maximum replica count.
7. IF a scrape of Fleet_Metric_Endpoint fails — returning HTTP 503, returning an authentication rejection, exceeding the 5 second timeout, or returning a body without a numeric metric value — THEN THE Scaled_Object SHALL leave the current replica count unchanged and SHALL NOT treat the failed scrape as a value of 0.
8. THE Scaled_Object SHALL govern only API_Deployment, leaving ARQ_Deployment and every Singleton_Deployment replica count unchanged.
9. THE Per_Pod_Call_Target value SHALL be a whole number in the range 1 to 120 inclusive, set from the measured value produced by the Load_Test in Requirement 10, and recorded in Deployment_Documentation together with the maximum replica count derived from it in criterion 5.
10. WHILE the current replica count is above the minimum replica count, IF the desired replica count computed in criterion 3 is lower than the current replica count, THEN THE Scaled_Object SHALL hold the current replica count until the desired count has stayed lower for a continuous stabilization window of at least 300 seconds before reducing replicas.
11. WHEN the scraped value has remained at or below the warm-buffer value for a continuous period of 300 seconds, THE Scaled_Object SHALL request the minimum replica count of 1.

### Requirement 4: Graceful Drain Before Pod Termination

**User Story:** As an operations engineer, I want pods to finish their live calls before shutting down, so that scale-down and deploys never disconnect a customer mid-conversation.

#### Acceptance Criteria

1. THE PreStop_Handler SHALL poll Drain_Endpoint on its own API_Pod at an interval of 5 seconds or less, with a per-poll timeout of 5 seconds or less, and SHALL return only when Drain_Endpoint reports an active-call count of 0 or when the 360-second drain deadline elapses, whichever occurs first.
2. THE PreStop_Handler SHALL send the devops secret header `X-SpinSci-Devops-Secret` with each poll, sourced from a Kubernetes Secret.
3. THE API_Deployment SHALL set `terminationGracePeriodSeconds` to at least 420 seconds, being the 360-second drain deadline of criterion 1 plus at least 60 seconds of post-drain shutdown allowance, so that an Active_Call of up to 360 seconds — twice the 180-second average handle time — completes before SIGKILL.
4. WHILE an API_Pod is executing its PreStop_Handler, THE API_Pod SHALL continue serving media for its existing Active_Calls, closing zero of those Active_Calls with WebSocket close code 1012 for the duration of the drain deadline.
5. WHILE an API_Pod is executing its PreStop_Handler, THE API_Pod SHALL report itself not-ready within 5 seconds of PreStop_Handler start, and the readiness probe configuration SHALL mark that API_Pod not-ready within 15 seconds of the first not-ready response so that Ingress_Layer stops sending it new connections.
6. WHEN an API_Pod is removed under Kubernetes control by scale-down, rolling update, node drain, or eviction, THE PreStop_Handler SHALL execute to completion or to the drain deadline before SIGTERM is delivered to the container, except when the API_Pod is force-deleted with a grace period of 0.
7. IF the 360-second drain deadline elapses while Active_Calls remain on an API_Pod, THEN THE API_Pod SHALL emit a log record naming the API_Pod and the residual active-call count, and THEN termination SHALL proceed.
8. THE API_Deployment rolling update strategy SHALL set `maxUnavailable` to 0 so that replacement API_Pods are ready before draining API_Pods are removed.
9. THE Scaled_Object SHALL define a scale-down stabilization window of at least 300 seconds so that a transient dip in Active_Calls does not remove an API_Pod that is about to receive new calls.
10. THE API_Deployment SHALL declare a PodDisruptionBudget with `maxUnavailable` of 1 API_Pod so that at most one API_Pod drains at a time during voluntary disruptions.
11. IF a poll of Drain_Endpoint returns a non-success status, returns a body from which an active-call count cannot be read, or exceeds its per-poll timeout, THEN THE PreStop_Handler SHALL treat that poll as reporting a non-zero active-call count and SHALL continue polling until Drain_Endpoint reports 0 or the drain deadline elapses.
12. WHERE `FASTAPI_WORKERS` is greater than 1, THE PreStop_Handler SHALL treat an API_Pod as drained only when the active-call count across every worker process in that API_Pod is 0, and SHALL NOT treat a single zero-valued poll response as evidence that the API_Pod holds no Active_Calls.

### Requirement 5: Single-Replica Handling for Singleton Components

**User Story:** As a platform operator, I want ari_manager and campaign_orchestrator to run exactly once, so that scaling the API tier does not duplicate Asterisk channel handling or campaign scheduling.

#### Acceptance Criteria

1. THE `ari_manager` process SHALL run as the sole long-running process of a Singleton_Deployment that is separate from API_Deployment, ARQ_Deployment, and every other Singleton_Deployment.
2. THE `campaign_orchestrator` process SHALL run as the sole long-running process of a Singleton_Deployment that is separate from API_Deployment, ARQ_Deployment, and every other Singleton_Deployment.
3. Every Singleton_Deployment SHALL declare `replicas: 1` and a `Recreate` update strategy, and SHALL declare no surge replica, so that at no instant do two pods of that Singleton_Deployment have a running container.
4. WHEN API_Deployment scales to any replica count between the Scaled_Object minimum and maximum, THE replica count of every Singleton_Deployment SHALL remain 1.
5. THE API_Deployment container SHALL start neither `ari_manager` nor `campaign_orchestrator`, and no API_Pod SHALL host either process.
6. WHERE `ENABLE_ARI_STASIS` is false, THE `ari_manager` Singleton_Deployment SHALL declare 0 replicas so that no `ari_manager` process runs anywhere in the deployment.
7. WHEN a Singleton_Deployment pod is terminated for any reason under Kubernetes control, including rolling update, node drain, and manual deletion, THE Singleton_Deployment SHALL allow that pod at least 60 seconds to complete its in-flight ARI event handling or campaign dial scheduling before SIGKILL, and the replacement pod SHALL start only after the previous pod's container has exited.
8. IF the process inside a Singleton_Deployment pod exits, THEN Kubernetes SHALL restore exactly one running replica of that Singleton_Deployment without any interval in which two replicas run concurrently.
9. IF a Singleton_Deployment is observed with more than one running replica, THEN the deployment verification SHALL record a failure, given that duplicate `ari_manager` replicas duplicate Asterisk channel handling and duplicate `campaign_orchestrator` replicas duplicate outbound campaign dials because deduplication state is held per process.

### Requirement 6: ARQ Background Workers as an Independent Deployment

**User Story:** As a platform operator, I want post-call background work scaled separately from call serving, so that a queue backlog does not require adding call-serving capacity.

#### Acceptance Criteria

1. THE ARQ_Deployment SHALL run all ARQ worker processes in pods created by a Kubernetes Deployment distinct from API_Deployment, such that no pod contains both an ARQ worker process and an API server process.
2. THE ARQ_Deployment replica count SHALL be settable to any integer from 0 to 50 with no change to API_Deployment replica count, and THE API_Deployment replica count SHALL be settable with no change to ARQ_Deployment replica count.
3. THE API_Deployment container SHALL start zero ARQ worker processes, with `ARQ_WORKERS` set to 0, verifiable by the absence of any ARQ worker process in a running API_Pod.
4. THE ARQ_Deployment SHALL connect to the same External_Datastore Redis instance and Postgres instance as API_Deployment, using the same connection configuration values.
5. WHEN an ARQ_Deployment pod receives SIGTERM, THE ARQ_Deployment pod SHALL stop claiming new jobs from the queue within 5 seconds and SHALL be granted a termination grace period of at least 60 seconds before SIGKILL.
6. IF an in-flight job has not completed when the 60-second grace period expires, THEN THE ARQ_Deployment SHALL leave that job claimable by a surviving worker and SHALL record an error indicating the job was interrupted.
7. IF the Redis instance or the Postgres instance is unreachable when an ARQ_Deployment pod starts, THEN THE ARQ_Deployment pod SHALL report itself not ready, SHALL claim no jobs, and SHALL retry the connection at intervals of at most 10 seconds.
8. WHILE the ARQ_Deployment replica count is 0, THE queued jobs SHALL remain in the Redis queue and SHALL be claimed for processing within 30 seconds of the replica count rising above 0.

### Requirement 7: Raising the Concurrency Ceiling

**User Story:** As a platform operator, I want the application's own concurrency limits raised to match the provisioned capacity, so that the autoscaler is not defeated by an application-level cap of 10.

#### Acceptance Criteria

1. THE API_Deployment SHALL set the `DEFAULT_ORG_CONCURRENCY_LIMIT` environment variable so that the value resolved in `api/constants.py` is 120, matching the provisioned headroom for a Per_Pod_Call_Target-based fleet sized for 90 concurrent calls.
2. IF the `DEFAULT_ORG_CONCURRENCY_LIMIT` environment variable is absent, non-numeric, zero, or negative, THEN THE API_Deployment SHALL resolve `DEFAULT_ORG_CONCURRENCY_LIMIT` to a value of at least 1 and SHALL start without raising an error.
3. WHEN THE Concurrency_Service resolves an organization's effective limit, THE Concurrency_Service SHALL use the per-organization `CONCURRENT_CALL_LIMIT` configuration value when that value is present and parses as an integer of 1 or greater, and SHALL otherwise use `DEFAULT_ORG_CONCURRENCY_LIMIT`.
4. IF reading the per-organization `CONCURRENT_CALL_LIMIT` configuration fails, THEN THE Concurrency_Service SHALL use `DEFAULT_ORG_CONCURRENCY_LIMIT` as the effective limit and SHALL complete the acquisition attempt rather than rejecting the call.
5. WHEN the number of Active_Calls for an organization equals that organization's effective limit and a further acquisition is attempted with no wait timeout remaining, THE Concurrency_Service SHALL reject that acquisition, SHALL leave the organization's Active_Calls count and the fleet-wide Active_Calls count unchanged, and SHALL surface an error indicating the concurrent call limit was reached.
6. WHEN the number of Active_Calls for an organization is 1 or more below that organization's effective limit, THE Concurrency_Service SHALL grant the acquisition and SHALL increment both the per-organization and fleet-wide Active_Calls counts by 1.
7. THE raised limit SHALL be applied through environment configuration only, leaving the Lua-scripted slot accounting in `api/services/call_concurrency/rate_limiter.py`, its per-organization and fleet counter key schema, and its 20-minute stale slot timeout unchanged.
8. Deployment_Documentation SHALL state the numeric relationship between the per-organization limit (120), Per_Pod_Call_Target, the Scaled_Object maximum replica count, and the 90 concurrent call target, such that a reader can compute maximum replicas from Per_Pod_Call_Target and the concurrency target.

### Requirement 8: External Stateful Services

**User Story:** As a platform operator, I want Postgres, Redis, and object storage running outside the application pods, so that scaling or replacing API pods never risks call state or stored recordings.

#### Acceptance Criteria

1. THE API_Deployment SHALL read `DATABASE_URL` pointing at an External_Datastore Postgres instance, and THE `pgvector` extension SHALL be installed in the target database before API_Deployment is started.
2. IF the `pgvector` extension is absent from the database named by `DATABASE_URL`, THEN THE API_Pod SHALL fail its readiness probe and SHALL emit a log record identifying the missing extension, rather than starting to serve traffic.
3. THE API_Deployment SHALL read `REDIS_URL` pointing at an External_Datastore Redis instance that permits server-side Lua script evaluation via `EVAL` for the credentials supplied to API_Deployment.
4. IF Redis rejects an `EVAL` invocation issued by Concurrency_Service, THEN THE Concurrency_Service SHALL reject the call acquisition that triggered it and SHALL emit a log record identifying the rejected script evaluation, leaving no partially written slot in the per-organization ZSET or the `concurrent_calls_fleet` ZSET.
5. THE API_Deployment SHALL read object-storage endpoint, credential, and bucket configuration pointing at an External_Datastore S3-compatible endpoint whose contents survive deletion and recreation of every API_Pod, ARQ_Deployment pod, and Singleton_Deployment pod.
6. THE Kubernetes application manifests SHALL declare no in-cluster Postgres, Redis, or MinIO workload, and no `emptyDir` or pod-local volume, as the storage location for call recordings, call audio, database state, or concurrency state.
7. Every API_Pod, every ARQ_Deployment pod, and every Singleton_Deployment pod SHALL resolve `REDIS_URL` to the same Redis instance and logical database so that Concurrency_Service slot accounting and the `concurrent_calls_fleet` ZSET describe the whole fleet.
8. IF a Redis command issued by Fleet_Metric_Endpoint fails or does not complete within 2 seconds, THEN Fleet_Metric_Endpoint SHALL respond with HTTP 503 within 5 seconds of the request and SHALL NOT respond with a call count of zero or with the buffer value alone.
9. WHEN Redis reachability is restored after an outage, THE Fleet_Metric_Endpoint SHALL return HTTP 200 with the current fleet call count within 30 seconds without requiring an API_Pod restart.
10. Deployment_Documentation SHALL state the required Redis availability posture as a maximum tolerated unavailability window in seconds, and SHALL state that while Redis is unavailable the Scaled_Object holds the replica count unchanged per Requirement 3 criterion 7 and new call acquisitions are rejected.

### Requirement 9: TURN and WebRTC Media Under Kubernetes

**User Story:** As a platform operator, I want browser WebRTC calls to keep working after the migration, so that embedded and in-app voice sessions traverse NAT as they do today.

#### Acceptance Criteria

1. THE Turn_Workload SHALL accept traffic from clients outside the cluster on UDP 3478, TCP 3478, UDP 5349, TCP 5349, and the contiguous UDP relay port range 49152-49200 inclusive, over a network path that delivers the original client IP address unmodified to the Turn_Workload, verified by comparing the client's public source address to the address observed by the Turn_Workload for each of the five port groups.
2. WHEN the API issues TURN credentials from `api/routes/turn_credentials.py`, THE Turn_Workload SHALL be reachable within 5 seconds at the hostname the API publishes as `TURN_HOST` on each URI returned in the `uris` field, and that hostname SHALL resolve to a publicly routable address.
3. THE Turn_Workload SHALL be configured with the identical byte-for-byte `TURN_SECRET` value supplied to API_Deployment, such that a credential pair generated by `api/routes/turn_credentials.py` is accepted by the Turn_Workload for the full `TURN_CREDENTIAL_TTL` window and rejected after the encoded expiration timestamp has passed.
4. THE Turn_Workload SHALL receive an `external-ip` value that is a publicly routable IPv4 address equal to the address to which `TURN_HOST` resolves, and SHALL NOT receive a cluster-internal or link-local address in 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, or 169.254.0.0/16.
5. WHERE `ENABLE_COTURN` is false, THE deployment SHALL create zero Turn_Workload replicas and allocate none of the ports listed in criterion 1, and THE API SHALL reject requests to the TURN credentials endpoint with an error response indicating that the TURN server is not configured, without generating credentials.
6. THE deployment SHALL document, for each supported `ENVIRONMENT` value and for both a set and an unset `SERVER_IP`, which ICE candidate types the API advertises and which it filters out, including the resulting media path when `FORCE_TURN_RELAY` is true.
7. WHERE `ENABLE_COTURN` is false, THE API SHALL report `turn_enabled` as false in the response body of `GET /api/v1/health`, and WHERE `ENABLE_COTURN` is true and the Turn_Workload is ready, THE API SHALL report `turn_enabled` as true.
8. IF `ENABLE_COTURN` is true AND `TURN_SECRET` is unset or an empty string, THEN THE deployment SHALL fail before the Turn_Workload accepts client traffic and SHALL surface an error identifying the missing TURN shared secret, leaving no partially configured Turn_Workload serving requests.
9. THE Turn_Workload SHALL run with a fixed replica count of 1 and SHALL be excluded from KEDA-driven autoscaling, so that the relay port range in criterion 1 is owned by exactly one instance.

### Requirement 10: Load Test and Measured Capacity Sizing

**User Story:** As a platform engineer, I want per-replica call capacity measured before sizing is finalized, so that replica counts and the KEDA per-pod target rest on data rather than an assumed figure.

#### Acceptance Criteria

1. THE Load_Test SHALL drive synthetic concurrent calls against a single API_Pod using a stepped concurrency ladder that starts at 5 simultaneous Active_Calls and increases in steps of 5 until either the criterion 3 lag thresholds are exceeded or 60 simultaneous Active_Calls is reached, holding each step for at least 300 seconds and sampling at intervals of at most 10 seconds, and SHALL record at each step the API_Pod CPU utilization in cores, resident memory in mebibytes, and the `loop_lag_p95_ms` and `loop_lag_max_ms` values reported by Drain_Endpoint for every worker process in the API_Pod.
2. THE Load_Test SHALL report the marginal CPU in millicores per Active_Call and the marginal resident memory in mebibytes per Active_Call, each computed as the change in the measured value between two recorded ladder steps divided by the change in Active_Calls between those steps, and SHALL report separately the idle per-pod CPU and resident memory measured at 0 Active_Calls after a warm-up of at least 60 seconds.
3. THE Load_Test SHALL identify the Measured_Sustainable_Concurrency as the highest ladder step at which, for the final 240 seconds of the step and for every worker process in the API_Pod, `loop_lag_p95_ms` remains at or below 150 ms and `loop_lag_max_ms` remains at or below 500 ms, with both thresholds recorded in the checked-in test definition.
4. THE Per_Pod_Call_Target used by Scaled_Object SHALL be an integer no greater than 80 percent of the Measured_Sustainable_Concurrency identified in criterion 3, and SHALL be at least 1.
5. THE API_Deployment memory and CPU `requests` SHALL each equal at least the idle per-pod value from criterion 2 plus the marginal per-call value from criterion 2 multiplied by Per_Pod_Call_Target, and the corresponding `limits` SHALL be at least 1.25 times those `requests` values.
6. THE Load_Test SHALL be executable from a definition checked into the repository with no manual step outside that definition, and SHALL record the container image tag or digest under test, the API_Pod CPU and memory `requests` and `limits` in effect during the run, the worker process count, and the run start timestamp.
7. WHEN Scaled_Object adds at least one API_Pod replica while the Load_Test is holding a concurrency step, THE Load_Test SHALL report the count of Active_Calls terminated during the scale-up, and that count SHALL be 0.
8. Deployment_Documentation SHALL record the idle per-pod CPU and memory, the marginal per-call CPU and memory, the Measured_Sustainable_Concurrency, the chosen Per_Pod_Call_Target, and the tested image tag or digest, and SHALL state that these figures supersede the unmeasured "300-500 MB RAM per worker" idle-overhead guidance in `docs/deployment/scaling.mdx` for the Kubernetes path.
9. IF the Load_Test exceeds the criterion 3 lag thresholds at the first ladder step, or terminates before completing at least one full 300-second step, THEN THE Load_Test SHALL report a failure result indicating that no Measured_Sustainable_Concurrency was established, SHALL retain the samples recorded up to that point, and Per_Pod_Call_Target SHALL remain unset in Scaled_Object.
10. IF the container image tag or digest deployed to API_Deployment differs from the value recorded in criterion 6, THEN Deployment_Documentation SHALL indicate that the recorded capacity figures are unvalidated for the deployed image.

### Requirement 11: Drain and Scale Correctness Verification

**User Story:** As a release manager, I want explicit evidence that scaling and deploying does not drop calls, so that I can ship changes during the business-hours window.

#### Acceptance Criteria

1. WHEN a rolling update of API_Deployment is performed while at least 20 Active_Calls are in progress across at least 2 API_Pods, THE verification procedure SHALL record zero Active_Calls closed with WebSocket close code 1012, and SHALL record that each of those Active_Calls remained connected until its own caller-initiated or agent-initiated completion.
2. WHEN Scaled_Object reduces the API_Deployment replica count while at least 20 Active_Calls are in progress, THE verification procedure SHALL record, for every removed API_Pod, a final Drain_Endpoint reading of 0 active calls observed before SIGTERM was delivered to that API_Pod, and zero Active_Calls closed with WebSocket close code 1012.
3. WHEN an Active_Call completes on any API_Pod, whether by normal hangup or by call-pipeline error, THE Concurrency_Service SHALL remove that call's slot from both the per-organization `concurrent_calls:{organization_id}` ZSET and the `concurrent_calls_fleet` ZSET within 60 seconds of completion.
4. WHEN the last Active_Call in the fleet has completed, THE Fleet_Metric_Endpoint SHALL report a value equal to the configured warm buffer, with no residual call count, within 60 seconds of that completion.
5. IF an API_Pod is deleted without executing its PreStop_Handler, THEN THE Concurrency_Service SHALL release that API_Pod's orphaned slots through its 20-minute stale-slot timeout, and Fleet_Metric_Endpoint SHALL report a value equal to the configured warm buffer within 21 minutes of the deletion.
6. THE verification results SHALL record, for each of criteria 1 through 5, an explicit pass or fail outcome, the container image version under test, the Active_Call count driven, the observed count of WebSocket close code 1012 terminations, and the completion timestamp.
7. THE verification procedure for criteria 1 through 5 SHALL be repeatable from a checked-in definition in the repository, so that a later image version can be verified by re-running it without reconstructing the steps.
8. IF any of criteria 1 through 5 records a fail outcome for an image version, THEN THE verification results SHALL mark that image version as not cleared for business-hours deployment, retaining the recorded outcomes rather than overwriting them.

### Requirement 12: Configuration and Secrets Management

**User Story:** As a platform operator, I want configuration and secrets managed as Kubernetes resources, so that I stop distributing a generated `.env` file to hosts.

#### Acceptance Criteria

1. THE Kubernetes manifests SHALL supply every non-sensitive configuration key that API_Deployment, ARQ_Deployment, and every Singleton_Deployment read at startup through ConfigMaps, SHALL define each key shared by two or more of those deployments once with a single value, and SHALL mount no `.env` file into any container.
2. THE Kubernetes manifests SHALL supply `OSS_JWT_SECRET`, `SPINSCI_DEVOPS_SECRET`, `TURN_SECRET`, `TELEPHONY_WS_TOKEN_SECRET`, datastore credentials, and object-storage credentials through Kubernetes Secrets, and SHALL define none of these keys in any ConfigMap.
3. THE Kubernetes manifests tracked in git SHALL reference secret values only by Secret name and key, containing no literal value for any key named in criterion 2, and a repeatable check SHALL fail with a non-zero exit status naming each offending file and key when a literal value is present.
4. THE PreStop_Handler and the Scaled_Object SHALL read `SPINSCI_DEVOPS_SECRET` from the same Kubernetes Secret name and key used by API_Deployment, so that a single rotation of that key keeps the drain poll in Requirement 4 and the KEDA scrape in Requirement 3 authenticated.
5. WHEN a ConfigMap value that the application reads at startup is changed, THE deployment procedure SHALL trigger a rolling update of every deployment consuming that ConfigMap, subject to the drain rules in Requirement 4 and the `maxUnavailable: 0` strategy in Requirement 4 criterion 8.
6. THE deployment SHALL keep per-organization STT, LLM, and TTS provider credentials in the database read through `api/services/configuration/`, adding no provider API key to any ConfigMap or Secret.
7. Deployment_Documentation SHALL state that `api/.env` remains the local-development configuration path and `api/.env.test` remains the test configuration path, that neither is used by the Kubernetes deployment, and SHALL list every ConfigMap key and Secret key required by each deployment.
8. IF a configuration key required at startup is absent or empty when a container starts, THEN THE container SHALL exit with a non-zero status within 30 seconds, SHALL emit a log record naming each missing key, and SHALL never report ready.
9. WHEN a value in a Secret named in criterion 2 is rotated, THE deployment procedure SHALL roll every deployment consuming that Secret subject to the drain rules in Requirement 4, and no Active_Call in progress at the start of the roll SHALL be terminated by the roll.

### Requirement 13: Telephony Provider Channel Capacity Confirmation

**User Story:** As a platform operator, I want the upstream trunk capacity confirmed, so that scaled cluster capacity is not wasted against a carrier-side cap that fails as silent call rejections.

#### Acceptance Criteria

1. THE Deployment_Readiness_Checklist SHALL record, for each telephony provider configured for production use among Twilio, Exotel, ARI/Asterisk, Vobiz, Vonage, Plivo, Cloudonix, and Telnyx, a dated written confirmation from that provider stating the maximum number of simultaneous channels the account supports, and SHALL mark that provider as confirmed only if the stated maximum is at least 120.
2. THE Deployment_Readiness_Checklist SHALL record, for each provider recorded under criterion 1, the provider's stated maximum call initiations per second alongside the per-organization rate limit value configured in Concurrency_Service for the one-second sliding window enforced by `acquire_token`.
3. IF a telephony provider rejects a call initiation because an account-level channel limit or call-initiation rate limit is reached, THEN THE API_Pod that initiated the call SHALL record a call-failure entry carrying the provider name and the provider-supplied rejection reason, distinguishable from network transport failures.
4. THE Deployment_Readiness_Checklist SHALL record the minimum number of distinct caller-ID numbers per organization and telephony configuration pool initialized through `initialize_from_number_pool` in `api/services/call_concurrency/rate_limiter.py` for which `acquire_from_number` returns a number for all 120 simultaneous outbound calls, together with the provider's stated maximum simultaneous calls permitted per caller ID.
5. IF a provider's stated maximum simultaneous channels is below 120, THEN THE Deployment_Readiness_Checklist SHALL record that value as the binding capacity cap, together with the Scaled_Object maximum replica count and per-organization concurrency limit derived from it.
6. IF a provider's stated maximum call initiations per second is below the rate limit configured in Concurrency_Service, THEN THE Deployment_Readiness_Checklist SHALL record the provider value as the binding limit and THE configured Concurrency_Service rate limit SHALL be set to no more than that value before production traffic is admitted.
7. IF a call initiation is rejected by a telephony provider for an account-level channel or rate limit, THEN THE Concurrency_Service SHALL release that call attempt's concurrency slot and its acquired caller-ID number so that neither remains counted as an Active_Call.

### Requirement 14: Operator Documentation for the Kubernetes Path

**User Story:** As an operator new to this deployment, I want documentation covering the Kubernetes path, so that I can install, scale, and deploy without reading manifests to infer intent.

#### Acceptance Criteria

1. Deployment_Documentation SHALL contain an install procedure for the Kubernetes deployment as a numbered sequence of steps that states the required prerequisites of a Kubernetes cluster, KEDA, and an Ingress_Layer controller, the External_Datastore instances to provision per Requirement 8, every Kubernetes Secret named in Requirement 12 criterion 2, and the order in which the checked-in manifests are applied, such that an operator can complete the install without opening a manifest file.
2. Deployment_Documentation SHALL contain an autoscaling section that names Fleet_Metric_Endpoint, states the configured Per_Pod_Call_Target as a number of simultaneous Active_Calls, states the configured warm buffer in units of calls, and states the configured minimum and maximum replica counts as numbers.
3. Deployment_Documentation SHALL contain a drain section that names Drain_Endpoint and the PreStop_Handler, states the configured `terminationGracePeriodSeconds` value in seconds, states the configured scale-down stabilization window in seconds, and states that a pod removed without draining severs its Active_Calls with WebSocket close code 1012.
4. Deployment_Documentation SHALL state that `ari_manager` and `campaign_orchestrator` each run as a Singleton_Deployment at exactly 1 replica, and SHALL state the observable consequence of running 2 replicas as duplicated Asterisk channel handling for `ari_manager` and duplicated campaign call scheduling for `campaign_orchestrator`.
5. Deployment_Documentation SHALL state that the Docker Compose path in `docker-compose.yaml` remains supported for single-host installs, and SHALL state the migration threshold as the number of simultaneous Active_Calls above which one host's measured capacity from Requirement 10 is exceeded.
6. Deployment_Documentation SHALL state that Pipecat Cloud hosting and a per-call container model are outside this deployment path, and SHALL state that changes to the per-organization STT, LLM, and TTS provider system are outside this deployment path.
7. Every numeric value stated in Deployment_Documentation for Per_Pod_Call_Target, warm buffer, minimum replicas, maximum replicas, `FASTAPI_WORKERS`, `terminationGracePeriodSeconds`, and the scale-down stabilization window SHALL equal the value declared in the checked-in Kubernetes manifests for the same setting.
8. Deployment_Documentation SHALL state, in the existing `docs/deployment/scaling.mdx` page, which of its guidance applies to the Docker Compose path only and SHALL link to the Kubernetes autoscaling and drain sections.
9. Deployment_Documentation SHALL contain an upgrade procedure stating how a new image version is rolled out under the Requirement 4 drain rules and how an operator observes that the rollout terminated zero Active_Calls.
