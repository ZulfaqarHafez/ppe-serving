#!/usr/bin/env bash
# Run every CI step on this machine, in the workflow's order, and keep a log
# with absolute paths replaced by <workspace>: results/ci_local.log.
# Behind a TLS-intercepting proxy set PPE_EXTRA_CA to its CA bundle for the
# image build (passed as a BuildKit secret).
set -euo pipefail
cd "$(dirname "$0")/.."
log=results/ci_local.log
mkdir -p results
ws=$(cd .. && pwd)
# uv renamed UV_NATIVE_TLS to UV_SYSTEM_CERTS; map it if the host still sets it.
if [ -n "${UV_NATIVE_TLS:-}" ]; then export UV_SYSTEM_CERTS=$UV_NATIVE_TLS; unset UV_NATIVE_TLS; fi
{
  echo "# scripts/ci_local.sh, $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  scripts/ci.sh tools lint typecheck lock model test image smoke k6-gate manifests actionlint
  echo "# all CI steps passed"
} 2>&1 | sed -e "s#$ws#<workspace>#g" -e "s#$HOME#<home>#g" -e 's#/tmp/[^ ]*#<tmp>#g' | tee "$log"
exit "${PIPESTATUS[0]}"
