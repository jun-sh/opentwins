#!/usr/bin/env bash
# Backfill bucket phm_agg from raw for [START, STOP) in 1 h chunks with the downsample task's own query.
# usage: scripts/influx-backfill.sh 2026-11-24T11:00:00Z 2026-11-26T16:00:00Z [thing_id regex, default all]
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
start=$(date -ud "$1" +%s); stop=$(date -ud "$2" +%s); things=${3:-.*}
body=$(sed -e '/^option task/d' -e "s#r.feature_id =~#r.thing_id =~ /${things}/ and r.feature_id =~#" influx/downsample-30s.flux)
for ((t = start; t < stop; t += 3600)); do
  a=$(date -ud "@$t" +%FT%TZ); b=$(date -ud "@$(( t + 3600 < stop ? t + 3600 : stop ))" +%FT%TZ)
  code=$(curl -s -o /tmp/phm-backfill.out -w '%{http_code}' -X POST "http://127.0.0.1:${PHM_INFLUX_PORT:-18086}/api/v2/query?org=phm" \
         -H "Authorization: Token $INFLUX_TOKEN" -H 'Content-Type: application/vnd.flux' -H 'Accept: application/csv' \
         --data-binary "${body/range(start: -3m)/range(start: $a, stop: $b)}")
  echo "$a .. $b  HTTP $code"; [ "$code" = 200 ] || { head -c 300 /tmp/phm-backfill.out; echo; exit 1; }
done
