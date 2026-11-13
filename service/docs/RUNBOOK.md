# Runbook: PPE detection service

How to roll the service out, roll it back, change the model, and read the
dashboard. Commands run from `service/`. Typical numbers below come from the
files under `results/`; they were measured on one 4-vCPU virtual machine, so
treat them as a shape to compare against, not as targets.

## Health at a glance

| Check | Healthy |
|---|---|
| `curl -s localhost:8000/readyz` | `{"status":"ready",...}`, HTTP 200 |
| `docker compose ps` | `ppe-service` shows `(healthy)` |
| `kubectl -n ppe get deploy,hpa` | all replicas available; HPA shows a CPU percentage, not `<unknown>` |
| Logs | one JSON line per request; no `"level":"error"` |

Startup logs `model checksum verified` then `ready` with the worker count. If
the container exits with code 3, the model file does not match the pinned
SHA-256: see "Change the model" below. Exit 2 means the model or manifest is
missing, exit 4 a bad `PPE_*` value (the log names it).

## Roll out

**Local stack.** `docker compose up -d --build`, then check `/readyz` and the
dashboard at http://127.0.0.1:3000.

**Kubernetes.**

1. Build and push the image with an immutable tag (CI's release job does this
   for a `v*` tag when `PUBLISH_IMAGE` is `'true'`).
2. Set the tag: `cd k8s/base && kustomize edit set image ghcr.io/zulfaqarhafez/ppe-service:<tag>`
   (or in the overlay you deploy).
3. Preview: `kubectl diff -k k8s/overlays/<env>`.
4. Apply and watch: `kubectl apply -k k8s/overlays/<env>` then
   `kubectl -n ppe rollout status deploy/ppe-service --timeout=180s`.
5. Confirm: `kubectl -n ppe get pods` all Ready; a test request returns the new
   `model.version` / `sha256`; the dashboard's error ratio stays at 0.

The Deployment rolls with `maxUnavailable: 0` and `maxSurge: 1`, so capacity
never drops below the current replica count. A new pod takes traffic only after
`/readyz` passes, which needs the model checksum to match. On the kind cluster a
rolling update of 2 replicas took 6 s (`results/k8s/rollout.txt`).

Each pod drains on shutdown: `preStop` sleeps 5 s so endpoints and kube-proxy
drop it first, then SIGTERM stops new connections and waits up to
`PPE_GRACEFUL_TIMEOUT_S` (20 s in the ConfigMap) for requests in flight. In
`results/shutdown.json` all 16 in-flight requests were answered during a stop.

## Roll back

**Kubernetes.** `kubectl -n ppe rollout undo deploy/ppe-service` (previous
revision) or `--to-revision=N` (see `kubectl -n ppe rollout history
deploy/ppe-service`), then `rollout status`. On kind a rollback took 6 s.
Afterwards set the image tag in git back to the same version, or the next
`apply` will roll forward again.

**Compose.** Point `image:` at the previous tag (or `docker tag` the previous
image as `ppe-service:dev`) and `docker compose up -d ppe-service`.

Roll back when, after a rollout: the error ratio rises above its baseline, p95
at the same load is clearly higher than before, pods restart (liveness
failures), or readiness never passes.

## Change the model

1. Put the new file somewhere reachable over HTTPS (see the README for Hugging
   Face Hub and object-store URL forms).
2. Update `registry/manifest.json`: `version`, `artifact.sha256`,
   `artifact.size_bytes`, `artifact.source`, `lineage`, and `metrics` with the
   file and key the numbers come from.
3. `uv run python scripts/fetch_model.py` (refuses a mismatch) and
   `PPE_REQUIRE_MODEL=1 uv run pytest -q`. The parity test pins the current
   model's answers on the five samples; a new model will change them, so
   regenerate the reference deliberately and say so in the commit.
4. Build, roll out as above, and check `ppe_model_info` on the dashboard.

`PPE_MODEL_SHA256` overrides the manifest's hash at run time; use it only to
pin, never to bypass a mismatch.

## Read the dashboard

Dashboard "PPE service" (provisioned from
`monitoring/grafana/dashboards/ppe-service.json`). Screenshot under load:
`docs/grafana-dashboard.png`.

| Panel | What it shows | How to read it |
|---|---|---|
| Throughput | `/v1/detect` requests per second, all statuses | On 2 CPUs the service saturated at about 24 req/s of real work (`results/loadtest/summary.md`). Much higher numbers usually mean fast 503s, so check the next panels. |
| p95 latency | Server-side p95 for `/v1/detect` | About 105 to 210 ms at 1 to 4 users on 2 CPUs. It falls during overload because 503s are fast; read it with the error ratio. |
| Error ratio | Share of `/v1/detect` responses that were not 200 | Should be 0. |
| In flight / Workers | Admitted requests now, and inference threads | In flight above Workers means requests are queueing. |
| Model | Version from `ppe_model_info` | Confirms which model a rollout loaded. |
| Requests per second by status | 200 against 503, 504, 4xx | 503 = in-flight cap reached; 504 = timeouts; 4xx = bad uploads. |
| Latency (server side) | p50, p95, p99 | p99 far above p95 suggests bursts or CPU throttling. |
| Stage time p95 | queue, decode, preprocess, inference, postprocess | Inference dominates a healthy request. A growing `queue` line is the saturation signal: add replicas or CPUs. A growing `decode` line points at large uploads. |
| In flight vs limit | `ppe_in_flight_requests` against `ppe_in_flight_limit` | At the limit, new requests get 503. |
| Errors by reason | `overloaded`, `timeout`, `too_large`, `too_many_pixels`, `unsupported_format`, `undecodable`, `empty`, `not_ready`, `internal` | `internal` is a bug: read the logs for that request id. |
| CPU used (cores) | Service process CPU | Pinned at the container's limit means CPU-bound; scale out. |
| Memory (RSS) | Resident memory | Should stay flat under steady load; steady growth would be a leak. |
| Detections per second by class | Output mix | A sudden shift with steady traffic can mean an input change (camera, lighting) or a different model. |

## Common situations

- **503 `overloaded` rising.** More concurrent requests than
  `PPE_MAX_IN_FLIGHT`. Scale out (the HPA does this on CPU) or raise the limit
  only if p95 at the limit is acceptable. Clients should back off: a flood of
  instant retries cost about a third of the served rate in the overload run
  (`results/dashboard_load.jsonl`).
- **New pods idle while one pod is hot.** Long-lived keep-alive connections:
  kube-proxy balances connections, not requests (`results/k8s/hpa.md`: with
  keep-alive, 4 pods and one of them served 100%). Use an L7 load balancer or
  service mesh, or make clients recycle connections.
- **504 `timeout`.** The request waited or ran longer than
  `PPE_REQUEST_TIMEOUT_S`; usually queueing under saturation. The work still
  finishes on its worker.
- **HPA shows `<unknown>`.** metrics-server is not answering; check
  `kubectl top pods` and the `v1beta1.metrics.k8s.io` APIService.
- **Logs.** `kubectl -n ppe logs deploy/ppe-service | grep <request id>`; each
  response carries `X-Request-ID`, and a caller-supplied id is kept.
