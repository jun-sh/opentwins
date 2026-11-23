#!/usr/bin/env bash
# Creates .env with random secrets and generates the nginx/mosquitto credential files. Idempotent.
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || cp .env.example .env

for key in DITTO_USER_PASSWORD DITTO_DEVOPS_PASSWORD INFLUX_ADMIN_PASSWORD GRAFANA_ADMIN_PASSWORD \
           MQTT_EDGE_PASSWORD MQTT_DITTO_PASSWORD MQTT_TELEGRAF_PASSWORD INFLUX_TOKEN; do
  if grep -qE "^${key}=$" .env; then
    len=16; [ "$key" = INFLUX_TOKEN ] && len=32
    sed -i "s|^${key}=$|${key}=$(openssl rand -hex "$len")|" .env
  fi
done
chmod 600 .env
set -a; . ./.env; set +a

mkdir -p secrets/mosquitto
printf 'ditto:%s\n' "$(openssl passwd -apr1 "$DITTO_USER_PASSWORD")" > secrets/nginx.htpasswd

# mosquitto_passwd runs inside the broker image so the file gets the owner/mode mosquitto expects.
docker run --rm -v "$PWD/secrets/mosquitto:/out" \
  -e E="$MQTT_EDGE_PASSWORD" -e D="$MQTT_DITTO_PASSWORD" -e T="$MQTT_TELEGRAF_PASSWORD" \
  docker.io/library/eclipse-mosquitto:2.1.4-alpine sh -c '
    rm -f /out/passwd &&
    mosquitto_passwd -c -b /out/passwd edge "$E" &&
    mosquitto_passwd -b /out/passwd ditto "$D" &&
    mosquitto_passwd -b /out/passwd telegraf "$T" &&
    chown mosquitto:mosquitto /out/passwd && chmod 0700 /out/passwd'

echo "init-env: .env and secrets/ ready"
