# Vulnerability summary (Grype)

Scanner: `docker.io/anchore/grype:v0.121.1`, vulnerability DB built 2026-11-23T06:28:32Z, scanned 2026-11-24. Counts are matches
(package x vulnerability); *fixable* = Critical/High with a fixed version upstream. Full JSON: `vulns/`.

| Image | Critical | High | Medium | Low | Other | Fixable C/H |
|---|---:|---:|---:|---:|---:|---:|
| `docker.io/eclipse/ditto-connectivity:3.9.9` | 0 | 8 | 430 | 55 | 0 | 8 |
| `docker.io/eclipse/ditto-gateway:3.9.9` | 0 | 6 | 426 | 55 | 0 | 6 |
| `docker.io/eclipse/ditto-policies:3.9.9` | 0 | 6 | 426 | 55 | 0 | 6 |
| `docker.io/eclipse/ditto-things:3.9.9` | 0 | 6 | 426 | 55 | 0 | 6 |
| `docker.io/eclipse/ditto-things-search:3.9.9` | 0 | 6 | 426 | 55 | 0 | 6 |
| `docker.io/eclipse/ditto-ui:3.9.9` | 16 | 63 | 10 | 0 | 0 | 69 |
| `docker.io/grafana/grafana:12.4.15` | 1 | 25 | 15 | 0 | 1 | 16 |
| `docker.io/library/eclipse-mosquitto:2.1.4-alpine` | 0 | 25 | 19 | 1 | 0 | 8 |
| `docker.io/library/influxdb:2.10.1-alpine` | 4 | 61 | 40 | 13 | 2 | 42 |
| `docker.io/library/mongo:7.0.48` | 3 | 43 | 237 | 21 | 18 | 46 |
| `docker.io/library/nginx:1.30.7-alpine` | 1 | 19 | 9 | 0 | 0 | 10 |
| `docker.io/library/python:3.11-slim-bookworm` | 4 | 99 | 162 | 29 | 111 | 7 |
| `docker.io/library/telegraf:1.40.3-alpine` | 1 | 22 | 13 | 0 | 1 | 2 |
| `phm-worker:0.1-offline` | 4 | 99 | 163 | 29 | 111 | 7 |
