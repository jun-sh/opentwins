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
  # PUT would replace the Thing and fail WoT validation (skeleton features missing) on re-run, so update attributes only if it exists.
  if curl -fs -o /dev/null -u "$DITTO_USER:$DITTO_USER_PASSWORD" "$BASE/api/2/things/$id"; then
    jq .attributes "$f" | put "$BASE/api/2/things/$id/attributes" "$DITTO_USER:$DITTO_USER_PASSWORD" -
  else
    put "$BASE/api/2/things/$id" "$DITTO_USER:$DITTO_USER_PASSWORD" "$f"
  fi
done

echo "influxdb:"  # bucket phm_agg (no expiry) + task phm-downsample-30s (created, or its flux updated)
IFX="http://127.0.0.1:${PHM_INFLUX_PORT:-18086}/api/v2"
ifx() { curl -fsS -H "Authorization: Token $INFLUX_TOKEN" -H 'Content-Type: application/json' "$@"; }
org=$(ifx "$IFX/orgs?org=phm" | jq -r '.orgs[0].id')
if ! ifx -o /dev/null "$IFX/buckets?orgID=$org&name=phm_agg" 2>/dev/null; then  # 404 when missing
  ifx -X POST "$IFX/buckets" -d "{\"orgID\":\"$org\",\"name\":\"phm_agg\",\"retentionRules\":[]}" >/dev/null
fi
echo "  bucket phm_agg"
flux=$(jq -Rs . < influx/downsample-30s.flux)
task=$(ifx "$IFX/tasks?orgID=$org&name=phm-downsample-30s" | jq -r '.tasks[0].id // empty')
if [ -n "$task" ]; then ifx -X PATCH "$IFX/tasks/$task" -d "{\"flux\":$flux}" >/dev/null
else ifx -X POST "$IFX/tasks" -d "{\"orgID\":\"$org\",\"flux\":$flux}" >/dev/null; fi
echo "  task phm-downsample-30s"
