#!/usr/bin/env bash
# Run every backend test in Docker, including the ones that need real Redis and PostgreSQL
# with pgvector. Uses throwaway containers on a throwaway network; nothing else is touched.
#   scripts/test_backend.sh            # all tests
#   scripts/test_backend.sh -k storage # extra pytest arguments
set -euo pipefail
cd "$(dirname "$0")/.."
repo="$(pwd -W 2>/dev/null || pwd)"   # Windows Git Bash needs the Windows-style path for -v
tag="agentsw-test-$$"
image="${TEST_IMAGE:-agent-sw-local-staging:latest}"

cleanup() {
  docker rm -f "$tag-redis" "$tag-pg" >/dev/null 2>&1 || true
  docker network rm "$tag" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker build -q -t "$image" ./backend >/dev/null
docker build -q -t agent-sw-postgres:16.15-pgvector0.8 ./infra/postgres >/dev/null
docker network create "$tag" >/dev/null
docker run -d --name "$tag-redis" --network "$tag" redis:7.4-alpine >/dev/null
docker run -d --name "$tag-pg" --network "$tag" -e POSTGRES_USER=test -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=migrations_test agent-sw-postgres:16.15-pgvector0.8 >/dev/null
for _ in $(seq 1 60); do
  docker exec "$tag-pg" pg_isready -U test -d migrations_test >/dev/null 2>&1 && break
  sleep 1
done
sleep 2

MSYS_NO_PATHCONV=1 docker run --rm --network "$tag" \
  -e REDIS_TEST_URL="redis://$tag-redis:6379/15" \
  -e POSTGRES_TEST_URL="postgresql+psycopg://test:test@$tag-pg:5432/migrations_test" \
  -v "$repo:/repo:ro" -w /repo/backend "$image" \
  python -m pytest -q -p no:cacheprovider -W ignore::Warning -rs "$@"
