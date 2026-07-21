#!/usr/bin/env bash
# Read-only readiness check for a future deployment - see docs/deployment.md
# and docs/gpu-demo-plan.md. Never changes anything and never deploys
# anything; it only reports what it finds, so it's safe to run on this Mac
# today, before any server exists, the same as it would be on a real VPS
# later. Every check is advisory (a WARN doesn't stop the script or return
# a non-zero exit code) except Docker itself being missing entirely.
set -uo pipefail

cd "$(dirname "$0")/../.."

PASS="[ OK ]"
WARN="[WARN]"

echo "=== Deployment preflight check ==="
echo

echo "--- Docker ---"
if command -v docker >/dev/null 2>&1; then
  echo "$PASS docker: $(docker --version)"
else
  echo "[FAIL] docker is not installed - nothing else here can run without it."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  echo "$PASS docker compose: $(docker compose version --short)"
else
  echo "[FAIL] 'docker compose' (the plugin, not standalone docker-compose) is not available."
  exit 1
fi
echo

echo "--- Architecture ---"
HOST_ARCH="$(uname -m)"
DOCKER_ARCH="$(docker info --format '{{.OSType}}/{{.Architecture}}' 2>/dev/null || echo "unknown")"
echo "$PASS host reports: $HOST_ARCH"
echo "$PASS docker engine reports: $DOCKER_ARCH"
if [[ "$DOCKER_ARCH" == *"aarch64"* || "$DOCKER_ARCH" == *"arm64"* ]]; then
  echo "$WARN images built here are arm64 - a cloud GPU server is almost always amd64/x86_64 and needs its own rebuild (see docs/gpu-demo-plan.md)."
fi
echo

echo "--- GPU ---"
if command -v nvidia-smi >/dev/null 2>&1; then
  echo "$PASS nvidia-smi found - running it:"
  nvidia-smi
else
  echo "$WARN nvidia-smi not found - no NVIDIA GPU/driver on this machine, ai-inference will run in CPU mode (see docs/gpu-demo-plan.md)."
fi
echo

echo "--- Production env file ---"
if [ -f .env.production ]; then
  echo "$PASS .env.production exists."
  LEFTOVER_KEYS="$(grep "changeme" .env.production 2>/dev/null | cut -d= -f1 || true)"
  if [ -n "$LEFTOVER_KEYS" ]; then
    echo "$WARN these keys still have a placeholder value, replace before deploying:"
    echo "$LEFTOVER_KEYS" | sed 's/^/       /'
  else
    echo "$PASS no leftover 'changeme' placeholder values found."
  fi
else
  echo "$WARN .env.production does not exist yet - copy .env.production.example and fill in real secrets before deploying."
fi
echo

echo "--- Example compose files ---"
for f in docker-compose.app-node.example.yml docker-compose.data-node.example.yml docker-compose.ops-node.example.yml; do
  if [ -f "$f" ]; then
    if docker compose -f docker-compose.yml -f "$f" config >/dev/null 2>&1; then
      echo "$PASS $f parses correctly alongside docker-compose.yml."
    else
      echo "[FAIL] $f does not parse - check its syntax."
    fi
  else
    echo "$WARN $f not found."
  fi
done
echo

echo "--- Disk space ---"
df -h . | awk 'NR==1{print "       "$0} NR==2{print "'"$PASS"' "$0}'
echo

echo "=== Done. This is an advisory check only - nothing was deployed or changed. ==="
