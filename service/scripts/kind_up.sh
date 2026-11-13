#!/usr/bin/env bash
# Create a one-node kind cluster, load the images, install metrics-server,
# deploy the kind overlay, and record the rollout and an in-cluster smoke
# request under results/k8s/.
#
#   docker build -t ppe-service:dev .   (first)
#   scripts/kind_up.sh
#   scripts/kind_hpa.sh                 (HPA under load, with and without keep-alive)
#   scripts/kind_down.sh
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=results/k8s
mkdir -p "$OUT"
NS=ppe

# SANDBOX-SPECIFIC: derived node image whose runc clamps negative oom_score_adj.
docker build -q -t ppe-kind-node:v1.33.1 k8s/kind/node >/dev/null
docker image inspect ppe-service:dev >/dev/null
docker image inspect registry.k8s.io/metrics-server/metrics-server:v0.7.2 >/dev/null 2>&1 \
  || docker pull -q registry.k8s.io/metrics-server/metrics-server:v0.7.2

# SANDBOX-SPECIFIC: kind copies the host's proxy variables into the node, where
# they break in-cluster traffic; create the cluster without them. The node then
# has no route out, so every image is loaded from an archive instead of pulled.
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u NO_PROXY -u no_proxy \
  kind create cluster --config k8s/kind/cluster.yaml --wait 180s
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
for img in ppe-service:dev registry.k8s.io/metrics-server/metrics-server:v0.7.2; do
  # One platform only: Docker's containerd image store would also export an
  # attestation manifest whose blobs are missing, which ctr import rejects.
  docker save --platform linux/amd64 "$img" -o "$tmp/image.tar"
  kind load image-archive "$tmp/image.tar" --name ppe
done

kubectl apply -k k8s/kind/metrics-server
kubectl -n kube-system rollout status deploy/metrics-server --timeout=180s

{
  echo "# kubectl apply -k k8s/overlays/kind   ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
  start=$(date +%s)
  kubectl apply -k k8s/overlays/kind
  kubectl -n "$NS" rollout status deploy/ppe-service --timeout=180s
  echo "rollout finished in $(( $(date +%s) - start )) s"
  echo
  echo "# rolling update (kubectl rollout restart), maxUnavailable 0 / maxSurge 1"
  kubectl -n "$NS" scale deploy/ppe-service --replicas=2
  kubectl -n "$NS" rollout status deploy/ppe-service --timeout=180s
  start=$(date +%s)
  kubectl -n "$NS" rollout restart deploy/ppe-service
  kubectl -n "$NS" rollout status deploy/ppe-service --timeout=180s
  echo "rolling update finished in $(( $(date +%s) - start )) s"
  echo
  echo "# rollback to the previous revision (kubectl rollout undo)"
  start=$(date +%s)
  kubectl -n "$NS" rollout undo deploy/ppe-service
  kubectl -n "$NS" rollout status deploy/ppe-service --timeout=180s
  echo "rollback finished in $(( $(date +%s) - start )) s"
  kubectl -n "$NS" rollout history deploy/ppe-service
  echo
  echo "# state"
  kubectl get nodes -o wide
  kubectl -n "$NS" get deploy,rs,pods,svc,hpa,pdb,configmap -o wide
  echo
  echo "# pod security and probes"
  kubectl -n "$NS" get deploy ppe-service -o jsonpath='{.spec.template.spec.securityContext}{"\n"}{.spec.template.spec.containers[0].securityContext}{"\n"}{.spec.template.spec.containers[0].resources}{"\n"}'
  echo
  echo "# events"
  kubectl -n "$NS" get events --sort-by=.lastTimestamp | tail -40
} 2>&1 | tee "$OUT/rollout.txt"

kubectl -n "$NS" create configmap ppe-smoke-sample \
  --from-file=plant-cctv.webp=tests/data/samples/plant-cctv.webp --dry-run=client -o yaml | kubectl apply -f -
kubectl delete -f k8s/kind/smoke-pod.yaml --ignore-not-found >/dev/null
kubectl apply -f k8s/kind/smoke-pod.yaml
kubectl -n "$NS" wait --for=jsonpath='{.status.phase}'=Succeeded pod/ppe-smoke --timeout=120s
kubectl -n "$NS" logs ppe-smoke | tee "$OUT/smoke.json"
kubectl delete -f k8s/kind/smoke-pod.yaml >/dev/null
