#!/usr/bin/env bash
# P5 air-gapped install: run from the extracted bundle directory (no registry or PyPI access needed).
#   ./install.sh [--target DIR] [--env KEY=VALUE]... [--rebuild] [--no-smoke]
# 1 verify SHA256SUMS  2 docker load + check every image ID against the bundle  3 unpack stack/ into DIR
# 4 init-env (only if DIR/stack/.env is missing; --env overrides e.g. ports)  5 up core and phm-analytics
# with the offline overlays (pull_policy: never, --no-build)  6 wait for Ditto, InfluxDB,
# Grafana  7 provision.sh  8 smoke-test.sh.
# --rebuild: rebuild the custom PHM worker image from the vendored wheels with `docker build --network none`
# instead of using the prebuilt ones (proves the source -> image path works offline).
set -euo pipefail
B=$(cd "$(dirname "$0")" && pwd)
TARGET=$PWD/opentwins; SMOKE=1; REBUILD=0; ENVS=()
while [ $# -gt 0 ]; do
  case $1 in
    --target) TARGET=$2; shift ;;
    --env) ENVS+=("$2"); shift ;;
    --rebuild) REBUILD=1 ;;
    --no-smoke) SMOKE=0 ;;
    *) sed -n '2,10p' "$0"; exit 2 ;;
  esac; shift
done
DC=${DOCKER_COMPOSE:-docker-compose}
log() { printf '[install] %s\n' "$*" >&2; }
die() { printf '[install] ERROR: %s\n' "$*" >&2; exit 1; }

log "1/8 verifying checksums"
(cd "$B" && sha256sum --quiet -c SHA256SUMS) || die "checksum mismatch: bundle is corrupt or modified"

log "2/8 loading images"
docker load -q -i "$B/images/images.tar.gz" >/dev/null
while read -r ref id _; do
  got=$(docker image inspect --format '{{.Id}}' "$ref" 2>/dev/null || true)
  [ "$got" = "$id" ] || die "$ref: image ID $got != bundle $id"
done < "$B/images/images.ids"
log "    $(wc -l < "$B/images/images.ids") images verified by ID"

log "3/8 unpacking stack into $TARGET"
mkdir -p "$TARGET"; tar -xf "$B/stack.tar" -C "$TARGET"
S=$TARGET/stack; cd "$S"

if [ "$REBUILD" = 1 ]; then
  log "    rebuilding custom images offline from vendored wheels"
  base=$(awk '$1 ~ /library\/python:/ {print $1}' "$B/images/images.ids")
  ctx=$(mktemp -d)
  for img in phm-worker; do
    rm -rf "$ctx/$img"; mkdir -p "$ctx/$img"
    cp -r "$B/python/wheels-$img" "$ctx/$img/wheels"
    cp "$B/python/$img.wheels.lock.txt" "$ctx/$img/requirements.lock.txt"
  done
  cp phm/phm_worker.py phm/thermal_model.py "$ctx/phm-worker/"
  tag() { awk -v n="$1" '$1 ~ n {print $1}' "$B/images/images.ids"; }
  docker build -q --network none --build-arg "BASE=$base" -f offline/docker/phm-worker.Dockerfile \
    -t "$(tag '^phm-worker:')" "$ctx/phm-worker" >/dev/null
  rm -rf "$ctx"
fi

log "4/8 environment"
if [ ! -f .env ]; then
  cp .env.example .env
  for kv in "${ENVS[@]}"; do
    k=${kv%%=*}; grep -q "^$k=" .env && sed -i "s|^$k=.*|$kv|" .env || echo "$kv" >> .env
  done
  ./scripts/init-env.sh
else
  log "    keeping existing $S/.env"
fi
set -a; . ./.env; set +a

log "5/8 starting compose projects (offline overlays)"
$DC -f docker-compose.yml -f offline/compose/core.offline.yml up -d --no-build
(cd phm && $DC -p phm-analytics --env-file ../.env -f docker-compose.yml \
   -f ../offline/compose/phm.offline.yml up -d --no-build)

log "6/8 waiting for services"
wait_http() { # wait_http <name> <url> <seconds>
  local i
  for ((i = 0; i < $3; i += 5)); do
    curl -fs -o /dev/null "$2" && { log "    $1 healthy ($2)"; return 0; }
    sleep 5
  done
  die "$1 not healthy after $3 s ($2)"
}
wait_http InfluxDB "http://127.0.0.1:${PHM_INFLUX_PORT}/health" 180
wait_http Grafana "http://127.0.0.1:${PHM_GRAFANA_PORT}/api/health" 180
wait_http Ditto "http://127.0.0.1:${PHM_HTTP_PORT}/health" 600

log "7/8 provisioning Ditto"
./scripts/provision.sh

if [ "$SMOKE" = 1 ]; then
  log "8/8 smoke test"
  ./scripts/smoke-test.sh
fi
log "done: stack in $S (bundle $(jq -r .name "$B/bundle.json" 2>/dev/null || basename "$B"))"
