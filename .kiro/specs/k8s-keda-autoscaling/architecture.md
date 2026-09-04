# K8s + KEDA Autoscaling — High-Level Architecture

Target topology for the Kubernetes migration of the voice platform, sized for 90 concurrent
calls with headroom to 120 (5000 calls/day, 8–9 hour window, 3-minute average handle time).

Detailed component design, time budgets, and correctness properties live in the design
document. This file is the orientation view.

## 1. System topology

```mermaid
flowchart TB
  subgraph clients["Clients"]
    carrier["Telephony carriers<br/>Twilio · Exotel · Vonage · Plivo<br/>Telnyx · Cloudonix · Vobiz · ARI"]
    browser["Browsers<br/>WebRTC embed / in-app"]
  end

  subgraph cluster["Kubernetes cluster"]
    ing["Ingress<br/>TLS termination · WebSocket upgrade<br/>3600s timeouts · least-loaded balancing"]

    subgraph apitier["API tier — autoscaled by KEDA"]
      pods["API pods (1..N)<br/>uvicorn, 1 worker per pod<br/>many in-process Pipecat call tasks<br/>preStop drain hook"]
    end

    keda["KEDA<br/>scales on fleet active-call count"]

    subgraph fixed["Fixed-scale workloads"]
      arq["ARQ workers<br/>post-call jobs only"]
      ari["ari-manager<br/>exactly 1 replica"]
      camp["campaign-orchestrator<br/>exactly 1 replica"]
    end

    turn["coturn<br/>1 replica · UDP relay<br/>bypasses HTTP ingress"]
  end

  subgraph external["External managed services"]
    pg[("Postgres<br/>+ pgvector")]
    rd[("Redis<br/>concurrency state<br/>+ autoscale signal")]
    s3[("S3-compatible<br/>object storage")]
  end

  carrier -->|"media WebSocket"| ing
  browser -->|"HTTPS + signaling WebSocket"| ing
  browser -->|"UDP / TCP media relay"| turn

  ing --> pods
  keda -->|"reads active-call metric"| pods
  keda -.->|"sets replica count"| apitier

  pods --> pg
  pods --> rd
  pods --> s3
  arq --> pg
  arq --> rd
  ari --> rd
  camp --> rd
```

Three things this view is meant to make obvious:

- **Only the API tier autoscales.** ARQ workers scale independently by hand; the two
  singletons stay pinned at one replica because duplicating them duplicates Asterisk channel
  handling and outbound campaign dials.
- **TURN sits outside the HTTP path.** It is UDP plus a relay port range and needs the real
  client source address, so it gets its own L4 exposure.
- **Redis is load-bearing twice.** It holds the concurrency slots that admit calls *and* the
  fleet counter that drives scaling, so its availability gates both.

## 2. Autoscaling control loop

```mermaid
flowchart LR
  calls["Live calls<br/>across all pods"] -->|"slot per call"| zset[("Redis<br/>fleet counter")]
  zset --> metric["Fleet metric endpoint<br/>active calls + warm buffer"]
  metric -->|"poll every 15s"| keda["KEDA"]
  keda -->|"desired = ceil(metric / calls-per-pod)"| hpa["HPA<br/>scale-up: immediate<br/>scale-down: 300s stabilization"]
  hpa --> pods["API pod count<br/>min 1 · max sized for 120 calls"]
  pods --> calls

  metric -.->|"unreadable → 503"| hold["Hold replica count<br/>never read as zero"]
  hold -.-> hpa
```

The calls-per-pod divisor is the one number everything else derives from, and it comes from a
load test rather than an estimate. Event-loop lag is the saturation signal, not CPU: all of a
pod's calls share one asyncio loop, so audio starts degrading while CPU still looks healthy.

## 3. Graceful drain on pod removal

The highest-risk path. uvicorn force-closes call WebSockets on SIGTERM, so any pod removal
that reaches SIGTERM with calls still attached cuts live conversations.

```mermaid
sequenceDiagram
  participant K8s as Kubernetes
  participant Hook as preStop hook
  participant Pod as API pod
  participant Ing as Ingress

  K8s->>Hook: pod marked for removal, run preStop
  Hook->>Pod: set drain flag
  Note over Pod: health endpoint now reports not-ready
  Pod-->>Ing: removed from ready endpoints
  Note over Ing: no new calls routed here<br/>existing calls keep streaming
  loop until zero active calls, or deadline
    Hook->>Pod: poll active-call count
  end
  Hook-->>K8s: drained
  K8s->>Pod: SIGTERM
  Note over Pod: exits with no calls attached
```

Kubernetes runs the preStop hook *before* SIGTERM, which is what makes this safe. The one case
it does not cover is a force delete or hard node loss: calls are cut and their Redis slots are
orphaned, then reclaimed automatically by the stale-slot timeout.

## 4. What changes from today

```mermaid
flowchart LR
  subgraph now["Today — single-host Docker Compose"]
    n1["one api container<br/>uvicorn + ARQ + both singletons"]
    n2["nginx across worker ports"]
    n3["postgres · redis · minio<br/>as containers"]
    n4["no autoscaling"]
  end

  subgraph next["Target — Kubernetes"]
    t1["four workloads<br/>api · arq · ari-manager · campaign-orchestrator"]
    t2["ingress across pod replicas"]
    t3["managed postgres · redis · object storage"]
    t4["KEDA on fleet active-call count"]
  end

  n1 --> t1
  n2 --> t2
  n3 --> t3
  n4 --> t4
```

The Pipecat runtime model is unchanged: many concurrent call tasks per process, scaled by
adding replicas of the same image. There is no per-call container rewrite, and the Compose path
stays supported for single-host installs.
