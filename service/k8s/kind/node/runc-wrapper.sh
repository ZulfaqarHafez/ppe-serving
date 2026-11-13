#!/bin/sh
# SANDBOX-SPECIFIC. Not needed on a normal Linux host or in CI.
#
# The sandbox this was built in runs Docker without CAP_SYS_RESOURCE, so runc
# cannot write the negative oom_score_adj values the kubelet asks for (for
# example -998 for system-node-critical pods). Every such container fails to
# start, and with it every pod. This wrapper clamps negative oomScoreAdj values
# in the OCI spec to 0 before handing over to the real runc; non-negative
# values (all ordinary pods) are left alone.
bundle=""
process=""
prev=""
for arg in "$@"; do
  case "$prev" in
    --bundle|-b) bundle="$arg" ;;
    --process|-p) process="$arg" ;;
  esac
  case "$arg" in
    --bundle=*) bundle="${arg#--bundle=}" ;;
    --process=*) process="${arg#--process=}" ;;
  esac
  prev="$arg"
done
clamp() { # file, jq path
  if [ -f "$1" ] && jq -e "($2 // 0) < 0" "$1" >/dev/null 2>&1; then
    jq "$2 = 0" "$1" > "$1.clamped" && mv "$1.clamped" "$1"
  fi
}
[ -n "$bundle" ] && clamp "$bundle/config.json" '.process.oomScoreAdj'
[ -n "$process" ] && clamp "$process" '.oomScoreAdj'
exec /usr/local/sbin/runc.real "$@"
