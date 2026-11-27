#!/usr/bin/env bash
# P5 proof: installs a bundle inside a throwaway Docker-in-Docker container started with --network none
# (no registry, no PyPI, empty image store), then checks Ditto/InfluxDB/Grafana health, the smoke test and
# live data from the P4 simulator. Removes only its own container and volume (KEEP=1 keeps them).
#   offline/test/offline-proof.sh <dist/...tar> [install.sh options, e.g. --rebuild]
set -euo pipefail
TAR=$(realpath "$1"); shift
NAME=opentwins-p5-proof; VOL=opentwins-p5-proof-docker; HARNESS=opentwins-p5-proof:harness
BN=$(basename "$TAR" .tar)
log() { printf '[proof] %s\n' "$*" >&2; }
x() { docker exec "$NAME" "$@"; }
cleanup() { [ "${KEEP:-0}" = 1 ] && return; docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm "$VOL" >/dev/null 2>&1 || true; }

log "building harness image (test tooling only; online)"
ctx=$(mktemp -d); cp "$(dirname "$0")/Dockerfile.harness" "$ctx/Dockerfile"; cp "$(command -v docker-compose)" "$ctx/"
docker build -q -t "$HARNESS" "$ctx" >/dev/null; rm -rf "$ctx"

cleanup; trap cleanup EXIT
log "starting isolated dockerd: --network none, own volume $VOL"
docker run -d --name "$NAME" --privileged --network none -e DOCKER_TLS_CERTDIR= \
  -v "$VOL:/var/lib/docker" -v "$(dirname "$TAR"):/bundle:ro" "$HARNESS" >/dev/null
for _ in $(seq 60); do x docker info >/dev/null 2>&1 && break; sleep 2; done
log "isolation: interfaces=$(x sh -c "ip -o link | awk -F': ' '{print \$2}' | tr '\n' ' '")images=$(x docker images -q | wc -l)"
if x curl -s -m 5 -o /dev/null https://registry-1.docker.io/v2/ || x curl -s -m 5 -o /dev/null https://pypi.org/simple/; then
  echo "network reachable inside the proof container; aborting" >&2; exit 1
fi
log "isolation: registry and PyPI unreachable (expected)"

x sh -c "mkdir -p /work && tar -xf /bundle/$BN.tar -C /work"
(cd "$(dirname "$TAR")" && sha256sum -c "$BN.tar.sha256" >&2)
x bash -c "cd /work/$BN && ./install.sh --target /work/opentwins $*"

log "post-install checks"
x bash -c 'set -e; cd /work/opentwins/stack; set -a; . ./.env; set +a
  echo "InfluxDB: $(curl -fs http://127.0.0.1:$PHM_INFLUX_PORT/health | jq -c "{status,version}")"
  echo "Grafana:  $(curl -fs http://127.0.0.1:$PHM_GRAFANA_PORT/api/health | jq -c "{database,version}")"
  A="Authorization: Token $INFLUX_TOKEN"; I=http://127.0.0.1:$PHM_INFLUX_PORT/api/v2
  echo "Buckets:  $(curl -fs -H "$A" "$I/buckets?org=phm" | jq -c "[.buckets[]|select(.type==\"user\")|{name,expireS:.retentionRules[0].everySeconds}]")"
  echo "Ditto:    $(curl -fs http://127.0.0.1:$PHM_HTTP_PORT/health | jq -c "{status}")"
  echo "Ditto UI: HTTP $(curl -s -o /dev/null -w %{http_code} http://127.0.0.1:$PHM_HTTP_PORT/ui/) image $(docker inspect --format {{.Config.Image}} $(docker ps -qf name=ditto-ui))"
  docker ps -q | xargs docker inspect -f "{{.Name}}\t{{.Config.Image}}\t{{.State.Status}} restarts={{.RestartCount}} health={{if .State.Health}}{{.State.Health.Status}}{{end}}" | sort
  for _ in $(seq 36); do docker logs phm-analytics-phm-worker-1 2>&1 | grep -q "^\[cycle\]" && break; sleep 5; done  # first cycle may predate provision
  docker logs phm-analytics-phm-worker-1 2>&1 | grep -q "^\[cycle\]" || { echo "phm-worker: no successful cycle in 180 s" >&2; exit 1; }
  echo "Tasks:    $(curl -fs -H "$A" "$I/tasks?org=phm" | jq -c "[.tasks[]|{name,status,lastRunStatus}]")"
  echo "phm-worker log tail:"; docker logs --tail 5 phm-analytics-phm-worker-1 2>&1'
log "PASS: offline install healthy in isolation"
