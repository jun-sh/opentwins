# PHM reference stack — P1

Central services of the digital-twin / PHM reference architecture (see `../planning/`).
All components are unmodified upstream images; this directory only holds configuration.

| Service | Image | Host port | Role |
|---|---|---|---|
| mosquitto | eclipse-mosquitto 2.1.4 | `0.0.0.0:11883` | edge → centre MQTT (auth + ACL) |
| Ditto (policies, things, things-search, connectivity, gateway, ui) + mongodb | eclipse/ditto 3.9.9, mongo 7.0.48 | — | twin state, WoT Type validation |
| nginx | nginx 1.30.7 | `127.0.0.1:18080` | Ditto API/UI (`/api`, `/ui/`) + Type library (`/models/`) |
| influxdb | influxdb 2.10.1 | `127.0.0.1:18086` | raw high-rate history (bucket `raw`) |
| telegraf | telegraf 1.40.3 | — | MQTT → InfluxDB, memory buffer |
| grafana | grafana 12.4.15 | `127.0.0.1:13000` | dashboards (folder *PHM*) |
| phm-worker (project `phm-analytics`) | built from `phm/` (python 3.11, progpy 1.9.0, pyod 3.6.9) | — | P3 PHM assessment every 120 s → Ditto `phm` |

## Run

```bash
./scripts/init-env.sh        # once: .env with random secrets, nginx/mosquitto credential files
docker-compose up -d
./scripts/provision.sh       # Ditto connection + policies + Things from connections/ and things/
./scripts/smoke-test.sh      # publishes fake Panda data, checks Ditto + InfluxDB
cd phm && docker-compose -p phm-analytics --env-file ../.env up -d --build   # PHM worker (-p is required: .env sets COMPOSE_PROJECT_NAME=phm)
```

InfluxDB measurements in bucket `raw`: `telemetry` (edge raw), `phm` (PHM results per feature), `event_frame` (abnormal episodes, `phase`=start/end), `phm_baseline` (fixed-baseline start per robot). Bucket `phm_agg` (no expiry): `telemetry_30s`, 30 s joint aggregates written every minute by the InfluxDB task `phm-downsample-30s` (`influx/downsample-30s.flux`, created by `provision.sh`); the PHM worker reads only this.

Credentials are in `.env` (git-ignored): Ditto `DITTO_USER` (default `admin`) / `DITTO_USER_PASSWORD`, Grafana `admin` / `GRAFANA_ADMIN_PASSWORD`.

## Edge contract (what an adapter must publish)

MQTT user `edge`, password `MQTT_EDGE_PASSWORD`.

| Topic | Payload | Rate | Consumer |
|---|---|---|---|
| `phm/raw/<thing_id>/<feature_id>` | `{"samples":[{"ts":<unix µs>,"<tm property>":<number>,...}]}` | batched high-rate | Telegraf → InfluxDB `telemetry`, tags `thing_id`, `feature_id` |
| `phm/state/<thing_id>` | Ditto Protocol `merge` on `/features` with `content-type: application/merge-patch+json`, `response-required: false` | 1–10 Hz | Ditto connection `phm-mqtt-ingest` |

Field names = WoT Thing Model property names; IDs = Ditto IDs. Ditto rejects a state message whose
Thing ID differs from the topic (connection enforcement) and any value violating the Thing Model.

## Type library

`type-library/` is served at `http://phm-models/models/...` inside the network and referenced from
Thing/Feature `definition`s. Ditto generates the Thing skeleton from the asset TM's `tm:submodel`s and
validates every write. Ditto blocks Thing Model downloads from private addresses by default; the
`things` service allow-lists only `phm-models`.

## Glue code register

| File | Lines | Purpose |
|---|---|---|
| `scripts/init-env.sh` | 31 | generate secrets and credential files |
| `scripts/provision.sh` | 54 | PUT declarative JSON to the Ditto API; InfluxDB bucket `phm_agg` + downsample task |
| `scripts/influx-backfill.sh` | 15 | fill `phm_agg` from raw for a past range (1 h chunks, same Flux as the task): `scripts/influx-backfill.sh <start> <stop> [thing regex]` |
| `influx/downsample-30s.flux` | 17 | InfluxDB task: raw joint telemetry → 30 s mean/min/max in `phm_agg` (config, not code) |
| `scripts/smoke-test.sh` | 27 | end-to-end check |
| `adapters/systemd/g1-adapter.service` | 15 | user unit for the adapter on the G1 jump host (config, not code) |
| `adapters/systemd/{panda,piperx}-sim-adapter.service` | 15 each | user units for the two sim adapters on the DGX; read `~/.config/phm-sim/env` (`OPENTWINS_STACK`, `MENAGERIE_DIR`, `MQTT_EDGE_PASSWORD`, mode 600). PiPER unit injects wear on `joint2`, both use a 24 h wear cycle (config, not code) |
| `adapters/g1_dds_mqtt.py` | 167 | G1 29-DoF DDS (`rt/lowstate`, `bmsstate`) → MQTT; subscribe-only. Run on the G1 jump host: `PYTHONPATH=<dir with paho> python g1_dds_mqtt.py --iface enp6s0 --mqtt-host <DGX>`; needs `MQTT_EDGE_PASSWORD`. Raw payload is compacted for the WiFi uplink: fast fields rounded, slow fields (voltage, temperatures, fault) only on change or every 100 ms |
| `phm/phm_worker.py` | 294 | P3 PHM worker, one loop over every robot in `PHM_THING_IDS` (joint Features `*_joint` or `jointN`): InfluxDB `phm_agg` 30 s aggregates → PyOD ECOD `anomalyScore` + ProgPy thermal `rulHours` → Ditto `phm` (HTTP merge patch), InfluxDB `phm` and `event_frame`, Ditto `conditionChanged` event; marks joints without fresh data `stale`; robots without joint temperatures (Franka FCI) get anomaly only, `rulHours` -1; robots in `PHM_FIXED_BASELINE` are scored against a fixed known-good period (`phm_baseline`), others against the last 6 h; 2-cycle raise / 0.8 clear hysteresis; `phm_worker.py <ISO time>...` replays history read-only. See `../planning/p3-phm.md` |
| `phm/thermal_model.py` | 73 | ProgPy `PrognosticsModel`: first-order joint thermal model, parameter fit, time to `maxTemperature` |
| `phm/Dockerfile`, `phm/docker-compose.yml` | 34 | worker image and its own compose project `phm-analytics` (config, not code) |
| `adapters/panda_franka_mqtt.py` | 248 | Franka Panda/FR3 libfranka `RobotState` (`read_once()` loop, ~1 kHz) → MQTT; read-only, never commands motion. `--backend pylibfranka` (FR3, system ≥ 5), `panda_py` (Panda, system 4.x), `sim` (MuJoCo Menagerie `franka_emika_panda` via `mujoco_sim.py`), `fake` (offline test). `python panda_franka_mqtt.py --backend <b> --robot-ip <FCI ip> --mqtt-host <DGX>`; needs `MQTT_EDGE_PASSWORD`. Not yet run on the real robot |
| `adapters/piperx_can_mqtt.py` | 267 | AgileX PiPER / PiPER X `piper_sdk` (SocketCAN) feedback → MQTT; read-only, never sends enable/mode/motion frames. `--backend sdk --sdk-version V3` (firmware ≥ 1.8-8; else V2), `sim` (MuJoCo Menagerie `agilex_piper`) or `fake`. `faultCode` = `foc_status` fault flags (bit 6, driver enabled, is a state and stays 0). `python piperx_can_mqtt.py --can can0 --mqtt-host <DGX>`; needs `MQTT_EDGE_PASSWORD`. Not yet run on the real arm |
| `adapters/mujoco_sim.py` | 87 | `--backend sim` for the Panda and PiPER adapters: Menagerie MJCF under its own position servos on a smooth pick-and-place-like trajectory (gravity carried by the drives), real-time; first-order winding/driver thermal model from torque², sensor noise, `--sim-wear JOINT=RATE` adds damping and friction per hour so PHM has a degradation to detect; `--sim-wear-cycle-h N` makes wear follow the UTC wall clock in N h cycles (survives restarts, resets each cycle). Needs `pip install mujoco` and a Menagerie checkout (`git clone --depth 1 --filter=blob:none --sparse https://github.com/google-deepmind/mujoco_menagerie && git -C mujoco_menagerie sparse-checkout set franka_emika_panda agilex_piper`; `--menagerie` or `MENAGERIE_DIR`). Demo data only |
| `offline/bundle.sh` | 201 | P5: `lock` pins images by registry digest + Python artifacts by sha256; `build` vendors wheels, builds custom images with `--network none`, `docker save`s, runs SBOM, writes versioned tarball + `SHA256SUMS` |
| `offline/install.sh` | 100 | P5: air-gapped install from an extracted bundle (checksums, `docker load`, image-ID check, init-env, 2 projects up with offline overlays, health wait, provision, smoke test; `--rebuild` rebuilds custom images offline) |
| `offline/sbom.sh` | 48 | P5: Syft CycloneDX SBOM per image (+ Python-only SBOM for custom images), Grype vulnerability JSON + summary |
| `offline/licence_summary.py` | 133 | P5: licence classes from the SBOMs + curated `components.json`; flags AGPL/SSPL/NOSA/non-OSI/unknown |
| `offline/test/offline-proof.sh`, `Dockerfile.harness` | 51 | P5 test only: installs a bundle in a throwaway Docker-in-Docker with `--network none` and checks health and smoke test |
| `offline/docker/*.Dockerfile`, `offline/compose/*.offline.yml` | 62 | P5 config: offline twin of `phm/Dockerfile` (wheels only, `--require-hashes`; keep in sync) and `pull_policy: never` overlays |

## P5 offline deployment and SBOM (`offline/`)

Air-gapped install of both compose projects (core `phm`, `phm-analytics`). Default compose files are unchanged and still work online;
offline runs add the overlays in `offline/compose/` (`pull_policy: never`, bundle image tags, `--no-build`).

```bash
# on a connected build host (same CPU arch as the target), from a clean, committed checkout
offline/bundle.sh lock          # only after a version bump: refresh images.lock + python/*.lock.txt, review, commit
offline/bundle.sh build         # -> offline/dist/opentwins-phm-offline-<date>-<commit>-<arch>.tar (+ .tar.sha256)
# on the air-gapped target (needs docker, docker-compose, bash, curl, openssl, python3, envsubst, jq)
sha256sum -c opentwins-phm-offline-*.tar.sha256 && tar -xf opentwins-phm-offline-*.tar
cd opentwins-phm-offline-*/ && ./install.sh --target /opt/opentwins [--env PHM_HTTP_PORT=28080] [--rebuild]
# proof in a throwaway Docker-in-Docker with --network none (does not touch the running stack)
offline/test/offline-proof.sh offline/dist/opentwins-phm-offline-*.tar --rebuild
```

- Pinning: `offline/images.lock` maps every image reference in the compose files and Dockerfiles to its registry
  digest (taken from the local images, i.e. what the DGX runs). `build` refuses a local tag whose image differs
  from the lock and never retags it. The bundle records image IDs; `install.sh` checks every loaded ID.
- Python: `offline/python/<image>.lock.txt` lists every PyPI artifact with sha256 (x86_64, cp311). `build`
  downloads with `--require-hashes`, turns the sdist-only package (`fastdtw`) into a wheel
  (their build backends come from PyPI at bundle time; sdists ship in `python/sdist/` for audit), writes a
  wheel lock, and builds `phm-worker:0.1-offline` with
  `docker build --network none` from `offline/docker/*.Dockerfile` (keep in sync with the online Dockerfiles).
- Bundle layout: `images/images.tar.gz` (`docker save` of every image), `images/images.ids`, `python/` (wheels, locks,
  sdists), `stack.tar` (`git archive HEAD stack`), `sbom/`, `bundle.json`, `install.sh`, `SHA256SUMS`.
- SBOM (Syft v1.56.0, CycloneDX JSON) and vulnerabilities (Grype v0.121.1), both pinned by digest; inside the bundle
  in `sbom/` and copied to the repo in `offline/sbom/`: `cyclonedx.tar.gz` (per-image and Python-only SBOMs),
  `licence-summary.md`, `licence-flags.csv` (every non-permissive or unknown package), `vuln-summary.md`.
  Curated product licences: `offline/components.json`.
- Limits: one arch per bundle (re-lock on arm64); secrets are generated on the target by `init-env.sh`, never
  bundled; the Grype report is as of the bundle date; upgrading an existing install keeps its `.env`.

## Known limits (P1)

- Telegraf uses a memory buffer (3M metrics ≈ 100 s of one G1 at ~30k metrics/s): a longer InfluxDB outage, or a Telegraf restart, loses raw samples. The disk buffer cannot sustain G1 rates (it made Telegraf stall and mosquitto drop ~75% of the raw stream), so do not switch back to it; the `telegraf-buffer` volume is now unused. Size `metric_buffer_limit` up when more robots are added.
- Panda gripper is not modelled; the Panda adapter is only tested with `--backend fake` (no robot access yet).
- MQTT ACLs are configured but not covered by the smoke test (MQTT 3.1.1 silently drops denied publishes).
