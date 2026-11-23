#!/usr/bin/env bash
# Applies declarative config to a running stack: Ditto connection(s), then policy + Thing per file in things/.
# Thing file name convention: <namespace>_<name>.json  ->  Thing ID <namespace>:<name>
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
BASE="http://127.0.0.1:${PHM_HTTP_PORT}"

echo -n "waiting for Ditto"
for _ in $(seq 1 90); do
  curl -fs "$BASE/health" >/dev/null 2>&1 && break
  echo -n "."; sleep 5
done
curl -fs "$BASE/health" >/dev/null || { echo " Ditto not healthy"; exit 1; }
echo " ok"

put() { # put <url> <user:pass> <file|->
  local code
  code=$(curl -s -o /tmp/phm-provision.out -w '%{http_code}' -u "$2" -X PUT "$1" \
         -H 'Content-Type: application/json' --data-binary "@$3")
  case "$code" in 2*) echo "  $code $1";; *) echo "  $code $1"; cat /tmp/phm-provision.out; echo; return 1;; esac
}

echo "connections:"
for f in connections/*.json; do
  id=$(jq -r .id "$f")
  envsubst '${MQTT_DITTO_PASSWORD}' < "$f" | put "$BASE/api/2/connections/$id" "devops:$DITTO_DEVOPS_PASSWORD" -
done

echo "things:"
for f in things/*_*.json; do
  name=$(basename "$f" .json); id="${name/_/:}"
  envsubst '${DITTO_USER}' < things/policy-robot.json | put "$BASE/api/2/policies/$id" "$DITTO_USER:$DITTO_USER_PASSWORD" -
  put "$BASE/api/2/things/$id"   "$DITTO_USER:$DITTO_USER_PASSWORD" "$f"
done
