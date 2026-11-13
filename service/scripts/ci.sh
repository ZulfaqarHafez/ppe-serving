#!/usr/bin/env bash
# CI steps, shared by .github/workflows/service.yml and scripts/ci_local.sh so
# the two run the same commands. Run from service/: scripts/ci.sh <step>...
#
# Steps: tools lint typecheck lock model test image smoke k6-gate manifests actionlint
set -euo pipefail
cd "$(dirname "$0")/.."

TOOLS=${CI_TOOLS:-.ci-tools}
export PATH="$PWD/$TOOLS/bin:$PATH"
IMAGE=${IMAGE:-ppe-service:ci}
PORT=${PORT:-18090}
K8S_VERSION=1.33.1
SAMPLE=tests/data/samples/plant-cctv.webp

fetch() { # url sha256 out
  curl -fsSL --retry 3 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c --quiet -
}

step_tools() {
  mkdir -p "$TOOLS/bin"
  local tmp; tmp=$(mktemp -d)
  fetch https://github.com/grafana/k6/releases/download/v1.0.0/k6-v1.0.0-linux-amd64.tar.gz \
    5eb2236bc76a3c5cced12aaf0fd76c4b1ceac5ea040c70388a3d272b46595b59 "$tmp/k6.tgz"
  tar -xzf "$tmp/k6.tgz" -C "$tmp" && mv "$tmp/k6-v1.0.0-linux-amd64/k6" "$TOOLS/bin/"
  fetch https://github.com/yannh/kubeconform/releases/download/v0.7.0/kubeconform-linux-amd64.tar.gz \
    c31518ddd122663b3f3aa874cfe8178cb0988de944f29c74a0b9260920d115d3 "$tmp/kc.tgz"
  tar -xzf "$tmp/kc.tgz" -C "$TOOLS/bin" kubeconform
  fetch "https://dl.k8s.io/release/v$K8S_VERSION/bin/linux/amd64/kubectl" \
    5de4e9f2266738fd112b721265a0c1cd7f4e5208b670f811861f699474a100a3 "$TOOLS/bin/kubectl"
  fetch https://github.com/rhysd/actionlint/releases/download/v1.7.7/actionlint_1.7.7_linux_amd64.tar.gz \
    023070a287cd8cccd71515fedc843f1985bf96c436b7effaecce67290e7e0757 "$tmp/al.tgz"
  tar -xzf "$tmp/al.tgz" -C "$TOOLS/bin" actionlint
  chmod +x "$TOOLS/bin/"*
  rm -rf "$tmp"
  k6 version | head -1; kubeconform -v; kubectl version --client | head -1; actionlint -version | head -1
}

step_lint() { uv run --frozen ruff check . && uv run --frozen ruff format --check .; }
step_typecheck() { uv run --frozen mypy; }

step_lock() {
  uv lock --check
  uv export --frozen --no-dev --no-emit-project --format requirements-txt --no-header --quiet \
    | diff -u requirements.lock - && echo "requirements.lock matches uv.lock"
}

step_model() { uv run --frozen python scripts/fetch_model.py; }
step_test() { PPE_REQUIRE_MODEL=1 uv run --frozen pytest -q; }

step_image() {
  local secret=()
  if [ -n "${PPE_EXTRA_CA:-}" ]; then secret=(--secret "id=extra_ca,src=$PPE_EXTRA_CA"); fi
  docker build "${secret[@]}" -t "$IMAGE" .
  docker image inspect "$IMAGE" --format 'image size: {{.Size}} bytes'
}

start_container() {
  docker rm -f ppe-ci >/dev/null 2>&1 || true
  docker run -d --name ppe-ci -p "127.0.0.1:$PORT:8000" "$@" "$IMAGE" >/dev/null
  for _ in $(seq 1 60); do
    if curl -sf "http://127.0.0.1:$PORT/readyz" >/dev/null; then return 0; fi
    sleep 1
  done
  docker logs ppe-ci; return 1
}

step_smoke() {
  start_container --read-only --tmpfs /tmp --cap-drop ALL
  trap 'docker rm -f ppe-ci >/dev/null 2>&1 || true' RETURN
  curl -sf "http://127.0.0.1:$PORT/healthz"; echo
  local answer; answer=$(mktemp)
  curl -sf -F "file=@$SAMPLE" "http://127.0.0.1:$PORT/v1/detect" > "$answer"
  python3 - "$answer" registry/manifest.json <<'PY'
import json, sys
body, manifest = (json.load(open(p)) for p in sys.argv[1:3])
labels = [d["label"] for d in body["detections"]]
assert labels == ["No-vest", "No-Helmet"], labels
assert body["model"]["sha256"] == manifest["artifact"]["sha256"]
print("detect ok:", labels, body["timing_ms"])
PY
  curl -sf "http://127.0.0.1:$PORT/metrics" | grep -E '^ppe_(model_info|http_requests_total)' | head -3
  for _ in $(seq 1 30); do
    status=$(docker inspect ppe-ci --format '{{.State.Health.Status}}')
    [ "$status" = healthy ] && break
    sleep 2
  done
  echo "docker healthcheck: $status"; [ "$status" = healthy ]
  docker inspect ppe-ci --format 'user: {{.Config.User}}'
  set +e
  docker run --rm -e PPE_MODEL_SHA256="$(printf '0%.0s' $(seq 64))" "$IMAGE" >/dev/null 2>&1
  rc=$?
  set -e
  echo "checksum mismatch exit code: $rc"; [ "$rc" = 3 ]
}

step_k6_gate() {
  start_container --cpus "${GATE_CPUS:-2}"
  trap 'docker rm -f ppe-ci >/dev/null 2>&1 || true' RETURN
  k6 run -q -e BASE_URL="http://127.0.0.1:$PORT" -e VUS=2 -e DURATION=5s loadtest/detect.js >/dev/null
  k6 run -q -e BASE_URL="http://127.0.0.1:$PORT" -e VUS="${GATE_VUS:-2}" \
    -e DURATION="${GATE_DURATION:-20s}" -e P95_MS="${GATE_P95_MS:-1000}" -e MAX_ERR=0.01 \
    -e LABEL="ci gate" loadtest/detect.js
}

step_manifests() {
  for dir in k8s/base k8s/overlays/kind; do
    echo "== $dir"
    kubectl kustomize "$dir" | kubeconform -strict -summary -kubernetes-version "$K8S_VERSION" -
  done
}

step_actionlint() { actionlint ../.github/workflows/service.yml && echo "actionlint ok"; }

[ $# -gt 0 ] || { sed -n '2,6p' "$0"; exit 2; }
for s in "$@"; do
  echo "::group::$s"
  "step_${s//-/_}"
  echo "::endgroup::"
done
