#!/usr/bin/env bash
# End-to-end check without a robot: publishes one raw batch and one state update for
# lab.robots:panda-001/joint1, then reads them back from InfluxDB and Ditto.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
BASE="http://127.0.0.1:${PHM_HTTP_PORT}"
THING="lab.robots:panda-001"
dc() { docker-compose "$@"; }

now_us=$(( $(date +%s%N) / 1000 ))
samples=$(python3 -c "import json,math;print(json.dumps({'samples':[{'ts':$now_us-(9-i)*1000,'position':math.sin(i/10),'velocity':0.1,'torque':1.0+i/100} for i in range(10)]}))")
state='{"topic":"lab.robots/panda-001/things/twin/commands/merge","headers":{"content-type":"application/merge-patch+json","response-required":false},"path":"/features","value":{"joint1":{"properties":{"status":{"position":0.42,"velocity":0.1,"torque":1.09}}}}}'

dc exec -T mosquitto mosquitto_pub -h localhost -u edge -P "$MQTT_EDGE_PASSWORD" -t "phm/raw/$THING/joint1" -m "$samples"
dc exec -T mosquitto mosquitto_pub -h localhost -u edge -P "$MQTT_EDGE_PASSWORD" -t "phm/state/$THING"       -m "$state"
sleep 4

fail=0
pos=$(curl -fs -u "$DITTO_USER:$DITTO_USER_PASSWORD" "$BASE/api/2/things/$THING/features/joint1/properties/status/position" || true)
[ "$pos" = "0.42" ] && echo "PASS ditto  joint1.status.position=$pos" || { echo "FAIL ditto  got '$pos'"; fail=1; }

cnt=$(dc exec -T influxdb influx query --org phm --token "$INFLUX_TOKEN" --raw \
  "from(bucket:\"raw\") |> range(start:-5m) |> filter(fn:(r)=> r.thing_id==\"$THING\" and r.feature_id==\"joint1\" and r._field==\"position\") |> count() |> keep(columns:[\"_value\"])" \
  | tr -d '\r' | awk -F, '$0 !~ /^#/ && $NF ~ /^[0-9]+$/ {v=$NF} END {print v}')
[ "${cnt:-0}" -ge 10 ] 2>/dev/null && echo "PASS influx joint1.position samples=$cnt" || { echo "FAIL influx samples='$cnt'"; fail=1; }
exit $fail
