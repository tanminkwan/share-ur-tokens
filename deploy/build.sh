#!/usr/bin/env bash
# Build the Agent Arena image once; every deploy/<peer>/docker-compose.yml only runs it (no build in compose).
#   deploy/build.sh                      -> agent-arena:latest
#   deploy/build.sh agent-arena:0.6      -> a tag of your choice (then ARENA_IMAGE=agent-arena:0.6 in each .env)
# --network host and the proxy variables of this shell (HTTP_PROXY, HTTPS_PROXY, NO_PROXY, lower case too): the build
# reaches the package index the way this machine does. Only the names are passed; docker reads the values from the
# environment, and these build args are not kept in the image.
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:-agent-arena:latest}"
ARGS=()
for v in HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
  if [ -n "${!v:-}" ]; then ARGS+=(--build-arg "$v"); fi
done
docker build --network host "${ARGS[@]}" -f deploy/image/Dockerfile -t "$TAG" .
echo "built $TAG"
