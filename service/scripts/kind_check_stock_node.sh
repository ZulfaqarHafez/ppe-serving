#!/usr/bin/env bash
# SANDBOX-SPECIFIC check: can a stock kindest/node cluster start here?
# Tries to create a throwaway cluster from the unmodified node image (keeping
# the node on failure), records kind's output and the container runtime's
# errors about oom_score_adj, then deletes it.
# Writes results/k8s/stock-node-check.txt.
set -uo pipefail
cd "$(dirname "$0")/.."
out=results/k8s/stock-node-check.txt
mkdir -p results/k8s
{
  echo "# kind create cluster with stock kindest/node:v1.33.1 ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
  env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u NO_PROXY -u no_proxy \
    kind create cluster --name ppe-stock --retain --wait 60s \
    --image kindest/node:v1.33.1@sha256:050072256b9a903bd914c0b2866828150cb229cea0efe5892e2b644d5dd3b34f \
    2>&1 | grep -vE '^ [•✓✗]|^$' | tail -8
  echo "kind exit code: ${PIPESTATUS[0]}"
  echo
  echo "# containerd and kubelet log lines mentioning oom_score_adj (first 4)"
  docker exec ppe-stock-control-plane sh -c \
    'journalctl -u containerd -u kubelet --no-pager 2>/dev/null' \
    | grep -m4 'oom_score_adj' | cut -c1-400
  echo
  echo "# kube-system containers as seen by the runtime"
  docker exec ppe-stock-control-plane crictl ps -a 2>/dev/null | head -12
} > "$out" 2>&1
kind delete cluster --name ppe-stock >/dev/null 2>&1
sed -e "s#$HOME#<home>#g" -i "$out"
cat "$out"
