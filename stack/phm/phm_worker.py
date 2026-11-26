"""PHM worker (P3): InfluxDB history -> ProgPy thermal RUL + PyOD anomaly score -> Ditto `phm` group.

Every PHM_PERIOD_S, for every joint Feature (`*_joint` or `jointN`) of each Thing in PHM_THING_IDS:
  * reads 30 s aggregates (temperatures, torque mean/min/max, velocity, faultCode) from InfluxDB `phm_agg`
  * anomalyScore = PyOD ECOD score of the last PHM_ASSESS_S, relative to the fitted threshold
    (1.0 = at the 'contamination' threshold), fit on the rest of the PHM_HISTORY_S window; for Things in
    PHM_FIXED_BASELINE (repetitive duty cycle) on a fixed known-good period instead (InfluxDB `phm_baseline`,
    so slow wear is not learnt away). Raised after 2 cycles over the limit, cleared below PHM_CLEAR_RATIO x limit
  * rulHours = ProgPy JointThermal time to configuration.maxTemperature at the recent mean load
    (-1 = not estimated: no fresh data, or the robot reports no joint temperatures, e.g. Franka FCI)
  * healthIndex = min(thermal margin (ProgPy event_state), anomaly factor); condition by thresholds
Writes: Ditto merge patch on /features (HTTP, OWNER user), InfluxDB measurement `phm` (for Grafana),
and Event Frames: InfluxDB measurement `event_frame` (phase=start/end) + Ditto `conditionChanged` event.
"""
import csv
import io
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone

import numpy as np
import requests
from pyod.models.ecod import ECOD

from thermal_model import JointThermal, fit, time_to_overheat_h

E = os.environ
THINGS = [t.strip() for t in E.get("PHM_THING_IDS", E.get("PHM_THING_ID", "lab.robots:g1-001")).split(",") if t.strip()]
JOINT_RE = re.compile(r"(_joint|^joint[0-9]+)$")  # G1 Menagerie names / Panda and PiPER joint1..N
DITTO = E.get("DITTO_URL", "http://nginx:80").rstrip("/")
DITTO_AUTH = (E.get("DITTO_USER", "admin"), E["DITTO_USER_PASSWORD"])
INFLUX = E.get("INFLUX_URL", "http://influxdb:8086").rstrip("/")
INFLUX_HDR = {"Authorization": f"Token {E['INFLUX_TOKEN']}"}
BUCKET, ORG = E.get("INFLUX_BUCKET", "raw"), E.get("INFLUX_ORG", "phm")
AGG = E.get("PHM_AGG_BUCKET", "phm_agg")
PERIOD = float(E.get("PHM_PERIOD_S", 120))
HISTORY = int(E.get("PHM_HISTORY_S", 6 * 3600))
ASSESS = int(E.get("PHM_ASSESS_S", 300))
STALE = int(E.get("PHM_STALE_S", 600))
REFIT = float(E.get("PHM_REFIT_S", 3600))
DEFAULT_TMAX = float(E.get("PHM_DEFAULT_MAX_TEMP", 80))  # placeholder until Unitree's limit is confirmed
HORIZON_H = float(E.get("PHM_RUL_HORIZON_H", 24))
# condition thresholds: (anomalyScore, rulHours) for watch / alert
WATCH = (float(E.get("PHM_WATCH_SCORE", 1.0)), float(E.get("PHM_WATCH_RUL_H", 8)))
ALERT = (float(E.get("PHM_ALERT_SCORE", 2.0)), float(E.get("PHM_ALERT_RUL_H", 1)))
FIXED = {t.strip() for t in E.get("PHM_FIXED_BASELINE", "").split(",") if t.strip()}
BASELINE_S = int(E.get("PHM_BASELINE_S", 2 * 3600))
CLEAR = float(E.get("PHM_CLEAR_RATIO", 0.8))
MODEL_REF = "phm-worker/0.1 progpy-JointThermal+pyod-ECOD"
# min/max/mean only: they are pushed down to the storage engine (stddev is not and times out at 1 kHz)
FIELDS = ["windingTemperature", "driverTemperature", "torque", "velocity", "torqueMin", "torqueMax", "faultCode"]
LEVEL = {"normal": 0, "watch": 1, "alert": 2, "fault": 3}

# 30 s aggregates written by the InfluxDB task phm-downsample-30s (stack/influx/downsample-30s.flux)
FLUX = """from(bucket: "{b}") |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r._measurement == "telemetry_30s" and r.thing_id == "{t}")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> keep(columns: ["_time", "feature_id", {cols}])
"""


def flux(query):
    r = requests.post(f"{INFLUX}/api/v2/query", params={"org": ORG}, data=query, timeout=300,
                      headers={**INFLUX_HDR, "Content-Type": "application/vnd.flux", "Accept": "application/csv"})
    r.raise_for_status()
    rows = []
    for block in r.text.replace("\r\n", "\n").split("\n\n"):
        if block.strip():
            rows += list(csv.DictReader(io.StringIO(block)))
    return rows


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_history(thing, now, start=None):
    cols = ", ".join(f'"{c}"' for c in FIELDS)
    per = {}
    start = now - HISTORY if start is None else start
    for row in flux(FLUX.format(b=AGG, start=iso(start), stop=iso(now + 1), t=thing, cols=cols)):
        f = row.get("feature_id")
        if not f or row.get("_time") in (None, "_time"):
            continue
        vals = [float(row[c]) if row.get(c) not in (None, "") else np.nan for c in FIELDS]
        per.setdefault(f, []).append((ts(row["_time"]), vals))
    return {f: (np.array([t for t, _ in v]), np.array([x for _, x in v])) for f, v in per.items()}


def influx_write(lines):
    if lines:
        requests.post(f"{INFLUX}/api/v2/write", params={"org": ORG, "bucket": BUCKET, "precision": "s"},
                      data="\n".join(lines), headers=INFLUX_HDR, timeout=30).raise_for_status()


def tag(v):
    return v.replace(",", r"\,").replace(" ", r"\ ").replace("=", r"\=")


def ditto(thing, method, path, **kw):
    r = requests.request(method, f"{DITTO}/api/2/things/{thing}{path}", auth=DITTO_AUTH, timeout=30, **kw)
    if r.status_code >= 300:
        print(f"[ditto] {method} {thing}{path} -> {r.status_code} {r.text[:300]}")
    return r


def anomaly_score(t, x, now, det=None):
    """Mean ECOD score of the assessment window / threshold. det: detector fitted on a fixed baseline;
    None = fit on the history before the window (sliding baseline)."""
    x = x[:, ~np.isnan(x).all(axis=0)]  # drop signals this robot does not report (e.g. temperatures)
    ok = ~np.isnan(x).any(axis=1)
    t, x = t[ok], x[ok]
    recent = t >= now - ASSESS
    if det is None:
        if recent.sum() == 0 or (~recent).sum() < 60:
            return None
        det = ECOD(contamination=0.01).fit(x[~recent])
    elif recent.sum() == 0 or det.ncols != x.shape[1]:
        return None
    thr = max(float(det.threshold_), 1e-9)
    return max(0.0, float(np.mean(det.decision_function(x[recent]))) / thr)


class Worker:
    def __init__(self, thing):
        self.thing = thing
        self.models, self.fitted_at, self.cond, self.frames, self.prev, self.det = {}, {}, {}, {}, {}, None
        self.restore_frames()

    def baseline(self, now, dry_run):
        """Per-joint ECOD fitted once on [from, from + PHM_BASELINE_S] ({} until that has passed)."""
        if self.det is not None:
            return self.det
        q = (f'from(bucket: "{BUCKET}") |> range(start: 0) |> filter(fn: (r) => r._measurement == "phm_baseline"'
             f' and r.thing_id == "{self.thing}" and r._field == "from") |> last()')
        rows = [r for r in flux(q) if r.get("_value") not in (None, "", "_value")]
        b0 = float(rows[0]["_value"]) if rows else None
        if b0 is None:  # first telemetry of this robot, skipping one minute of start-up
            q = (f'from(bucket: "{AGG}") |> range(start: 0) |> filter(fn: (r) => r._measurement == "telemetry_30s"'
                 f' and r.thing_id == "{self.thing}" and r._field == "torque") |> first() |> group() |> min(column: "_time")')
            first = [r["_time"] for r in flux(q) if r.get("_time") not in (None, "", "_time")]
            if not first:
                return {}
            b0 = ts(first[0]) + 60
            if not dry_run:
                influx_write([f"phm_baseline,thing_id={tag(self.thing)} from={b0} {int(now)}"])
        if now < b0 + BASELINE_S + ASSESS:
            return {}
        det = {}
        for f, (t, x) in load_history(self.thing, b0 + BASELINE_S, start=b0).items():
            x = x[:, :6][:, ~np.isnan(x[:, :6]).all(axis=0)]; x = x[~np.isnan(x).any(axis=1)]  # as anomaly_score
            if len(x) >= 60:
                det[f] = ECOD(contamination=0.01).fit(x)
                det[f].ncols = x.shape[1]
        print(f"[baseline] {self.thing}: {iso(b0)} + {BASELINE_S} s, {len(det)} joints")
        self.det = det or None  # nothing to fit (no aggregates there yet): look again next cycle
        return det

    def restore_frames(self):
        """Reopen Event Frames whose last record is a start (survives restarts)."""
        q = (f'from(bucket: "{BUCKET}") |> range(start: -30d) |> filter(fn: (r) => r._measurement == "event_frame"'
             f' and r.thing_id == "{self.thing}") |> last() |> pivot(rowKey: ["_time"], columnKey: ["_field"],'
             f' valueColumn: "_value") |> keep(columns: ["_time", "feature_id", "phase", "condition"])')
        for row in flux(q):
            if row.get("phase") == "start":
                self.frames[row["feature_id"]] = ts(row["_time"])
                self.cond[row["feature_id"]] = row.get("condition", "watch")
        print(f"[init] {self.thing}: open event frames: {sorted(self.frames)}")

    def thermal(self, f, t, x, tmax):
        m = self.models.setdefault(f, JointThermal())
        m.parameters["t_max"] = tmax
        if np.isnan(x[:, 0:2]).all():
            return math.nan, -1.0, 1.0  # no temperature signal: thermal RUL not estimated
        hot = np.nanmax(x[:, 0:2], axis=1)
        load = np.nan_to_num(x[:, 2]) ** 2 + (np.nan_to_num(x[:, 5] - x[:, 4]) / 2) ** 2  # mean^2 + ~spread^2
        ok = ~np.isnan(hot)
        if time.time() - self.fitted_at.get(f, 0) > REFIT:
            seg = ok & (t >= t[-1] - 2 * 3600)
            if fit(m, t[seg].tolist(), hot[seg].tolist(), load[seg].tolist()):
                print(f"[fit] {self.thing}/{f}: " + ", ".join(f"{k}={float(m.parameters[k]):.3g}" for k in ("tau", "k", "t_amb")))
            self.fitted_at[f] = time.time()
        recent = ok & (t >= t[-1] - ASSESS)
        t_now, u = float(hot[ok][-1]), float(np.mean(load[recent])) if recent.any() else 0.0
        margin = float(m.event_state({"t": t_now})["overheat"])
        return t_now, time_to_overheat_h(m, t_now, u, HORIZON_H), margin

    def classify(self, score, prev, rul, fault, t_now, tmax, old):
        if fault or t_now >= tmax:
            return "fault", "faultCode" if fault else "temperature >= maxTemperature"
        for name, (s_lim, r_lim) in (("alert", ALERT), ("watch", WATCH)):
            if 0 <= rul < r_lim:
                return name, f"rulHours {rul:.2f} < {r_lim}"
            if score is not None and min(score, prev or 0.0) >= s_lim:  # raise: 2 cycles over the limit
                return name, f"anomalyScore {score:.2f} >= {s_lim}"
            if score is not None and LEVEL[old] >= LEVEL[name] and score >= CLEAR * s_lim:  # hold
                return name, f"anomalyScore {score:.2f} >= {CLEAR} x {s_lim}"
        return "normal", ""

    def event_frame(self, f, old, new, reason, now, lines):
        ditto(self.thing, "POST", f"/features/{f}/outbox/messages/conditionChanged", params={"timeout": "0"},
              data=json.dumps({"from": old, "to": new, "reason": reason}),
              headers={"Content-Type": "application/json"})
        base = f"event_frame,thing_id={tag(self.thing)},feature_id={tag(f)}"
        if old == "normal":
            self.frames[f] = now
            lines.append(f'{base} phase="start",condition="{new}",reason="{reason}" {int(now)}')
        elif new == "normal" and f in self.frames:
            dur = now - self.frames.pop(f)
            lines.append(f'{base} phase="end",condition="{old}",reason="recovered",durationS={dur:.0f} {int(now)}')
        print(f"[frame] {self.thing}/{f}: {old} -> {new} ({reason})")

    def cycle(self, now=None, dry_run=False):
        """One assessment as of `now` (default: wall clock). dry_run prints instead of writing."""
        started, now = time.time(), now or time.time()
        feats = ditto(self.thing, "GET", "/features").json()
        det = self.baseline(now, dry_run) if self.thing in FIXED else None  # then only the thermal fit's 2 h:
        hist = load_history(self.thing, now, start=None if det is None else now - 2 * 3600 - ASSESS)
        patch, lines, stale = {}, [], []
        stamp = iso(now)
        for f in sorted(k for k in feats if JOINT_RE.search(k)):
            t, x = hist.get(f, (np.array([]), None))
            if not len(t) or now - t[-1] > STALE:
                # No fresh data: the TM condition enum has no "unknown", so keep the last assessment
                # (lastAssessedAt shows its age), mark RUL "not estimated" (-1) and flag it in InfluxDB.
                stale.append(f)
                if feats[f].get("properties", {}).get("phm", {}).get("rulHours", -1) != -1:
                    patch[f] = {"properties": {"phm": {"rulHours": -1}}}
                lines.append(f'phm,thing_id={tag(self.thing)},feature_id={tag(f)} conditionLevel=-1i,condition="stale" {int(now)}')
                continue
            tmax = feats[f].get("properties", {}).get("configuration", {}).get("maxTemperature", DEFAULT_TMAX)
            fault = bool(np.nanmax(x[t >= now - ASSESS, 6], initial=0) > 0)
            t_now, rul, margin = self.thermal(f, t, x, tmax)
            if det is not None and f not in det:
                score = None  # fixed baseline not available yet (reference period still running)
            else:
                score = anomaly_score(t, x[:, :6], now, det[f] if det is not None else None)
            hi = min(margin, 1.0 - min(1.0, max(0.0, (score or 0.0) - 1.0) / 2.0))
            old = self.cond.get(f, "normal")
            cond, reason = self.classify(score, self.prev.get(f), rul, fault, t_now, tmax, old)
            self.prev[f] = score
            phm = {"healthIndex": round(hi, 4), "anomalyScore": round(score or 0.0, 4),
                   "rulHours": round(rul, 3), "condition": cond, "lastAssessedAt": stamp, "modelRef": MODEL_REF}
            patch[f] = {"properties": {"phm": phm}}
            temp = f",temperature={t_now}" if math.isfinite(t_now) else ""
            lines.append(f"phm,thing_id={tag(self.thing)},feature_id={tag(f)} healthIndex={phm['healthIndex']},"
                         f"anomalyScore={phm['anomalyScore']},rulHours={phm['rulHours']},"
                         f"conditionLevel={LEVEL[cond]}i,condition=\"{cond}\"{temp} {int(now)}")
            if cond != old and dry_run:
                print(f"  [frame] {f}: {old} -> {cond} ({reason})")
            elif cond != old:
                self.event_frame(f, old, cond, reason, now, lines)
            self.cond[f] = cond
        if dry_run:
            for f, p in patch.items():
                print(f"  {f:28s} {json.dumps(p['properties']['phm'])}")
            print(f"[dry-run] {self.thing} {iso(now)}: assessed {sum(f not in stale for f in patch)}, stale {len(stale)}")
            return
        if patch:
            ditto(self.thing, "PATCH", "/features", data=json.dumps(patch), headers={"Content-Type": "application/merge-patch+json"})
        influx_write(lines)
        print(f"[cycle] {self.thing} {iso(now)} assessed {sum(f not in stale for f in patch)}, stale {len(stale)}, "
              f"{time.time() - started:.1f}s; open frames {len(self.frames)}", flush=True)


def main():
    if len(sys.argv) > 1:  # replay: phm_worker.py <ISO time> [...]  -> dry-run assessments as of past times
        for thing in THINGS:
            w = Worker(thing)
            for a in sys.argv[1:]:
                w.cycle(now=ts(a), dry_run=True)
        return
    workers = {}
    while True:
        start = time.time()
        for thing in THINGS:  # one robot failing (offline, not provisioned) must not stop the others
            try:
                workers[thing] = workers.get(thing) or Worker(thing)
                workers[thing].cycle()
            except Exception as e:  # noqa: BLE001 - keep running; next cycle retries
                print(f"[error] {thing}: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        time.sleep(max(5.0, PERIOD - (time.time() - start)))


if __name__ == "__main__":
    main()
