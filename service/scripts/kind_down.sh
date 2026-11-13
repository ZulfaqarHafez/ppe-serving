#!/usr/bin/env bash
# Delete the kind cluster created by scripts/kind_up.sh.
set -euo pipefail
kind delete cluster --name ppe
