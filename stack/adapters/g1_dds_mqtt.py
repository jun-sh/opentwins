#!/usr/bin/env python3
"""Unitree G1 (29 DoF) DDS -> MQTT adapter. Subscribe-only: never publishes to any DDS topic.

rt/lowstate (~1 kHz)   -> phm/raw/<thing>/<joint>   batched samples (InfluxDB via Telegraf)
rt/lowstate + bmsstate -> phm/state/<thing>         Ditto merge patch at --state-hz
Topic/payload contract: stack/README.md. Run with the SDK interpreter plus paho-mqtt on PYTHONPATH.
"""
import argparse, json, os, threading, time

from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelSubscriber
from unitree_sdk2py.idl.unitree_hg.msg.dds_ import BmsState_, LowState_, MainBoardState_

# Menagerie unitree_g1 joint names; list index == DDS motor index 0-28.
JOINTS = [f"{s}_{j}_joint" for s in ("left", "right") for j in
          ("hip_pitch", "hip_roll", "hip_yaw", "knee", "ankle_pitch", "ankle_roll")]  # legs: left 0-5, right 6-11
JOINTS += ["waist_yaw_joint", "waist_roll_joint", "waist_pitch_joint"]
for side in ("left", "right"):
    JOINTS += [f"{side}_{j}_joint" for j in
               ("shoulder_pitch", "shoulder_roll", "shoulder_yaw", "elbow", "wrist_roll", "wrist_pitch", "wrist_yaw")]
assert len(JOINTS) == 29

# Unit assumptions for BmsState_ (verify with --dry-run on the robot): mV and mA.
BMS_V_SCALE, BMS_I_SCALE, N_CELLS, N_TEMPS = 1e-3, 1e-3, 13, 4


class Adapter:
    def __init__(self, a):
        self.a, self.lock = a, threading.Lock()
        self.raw = [[] for _ in JOINTS]      # pending raw samples per joint
        self.latest = None                   # latest LowState_ motor snapshot
        self.bms = None
        self.board = None
        self.n_msgs, self.n_lost, self.last_tick = 0, 0, None
        self.mqtt = None if a.dry_run else self._mqtt()

    def _mqtt(self):
        import paho.mqtt.client as mqtt
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"g1-adapter-{os.getpid()}")
        except AttributeError:  # paho-mqtt 1.x
            c = mqtt.Client(client_id=f"g1-adapter-{os.getpid()}")
        c.username_pw_set(self.a.mqtt_user, os.environ["MQTT_EDGE_PASSWORD"])
        c.connect(self.a.mqtt_host, self.a.mqtt_port, keepalive=30)
        c.loop_start()
        return c

    # --- DDS callbacks: keep them tiny, they run at ~1 kHz ---
    def on_lowstate(self, m):
        ts = time.time_ns() // 1000
        tick = m.tick
        with self.lock:
            if self.last_tick is not None and tick > self.last_tick:
                self.n_lost += tick - self.last_tick - 1  # tick increments by 1 per control cycle
            self.last_tick = tick
            self.n_msgs += 1
            ms = m.motor_state
            for i in range(29):
                s = ms[i]
                self.raw[i].append({"ts": ts, "position": s.q, "velocity": s.dq, "torque": s.tau_est,
                                    "busVoltage": s.vol, "windingTemperature": s.temperature[0],
                                    "driverTemperature": s.temperature[1], "faultCode": s.motorstate})
            self.latest = [(s.q, s.dq, s.tau_est, s.vol, s.temperature[0], s.temperature[1], s.motorstate)
                           for s in ms[:29]]
            self.mode_machine = m.mode_machine

    def on_bms(self, m):
        self.bms = m

    def on_board(self, m):
        self.board = m

    # --- publishing ---
    def _pub(self, topic, payload):
        if self.mqtt is None:
            print(topic, payload[:300])
        else:
            self.mqtt.publish(topic, payload, qos=0)

    def flush_raw(self):
        with self.lock:
            batches, self.raw = self.raw, [[] for _ in JOINTS]
        for name, samples in zip(JOINTS, batches):
            if samples:
                self._pub(f"phm/raw/{self.a.thing}/{name}", json.dumps({"samples": samples}))

    def publish_state(self):
        with self.lock:
            snap, mode = self.latest, getattr(self, "mode_machine", None)
        if snap is None:
            return
        feats = {}
        for name, (q, dq, tau, vol, t0, t1, fault) in zip(JOINTS, snap):
            feats[name] = {"properties": {"status": {
                "position": q, "velocity": dq, "torque": tau, "busVoltage": vol,
                "windingTemperature": t0, "driverTemperature": t1, "faultCode": int(fault)}}}
        b = self.bms
        if b is not None:
            st = {"soc": b.soc, "soh": b.soh, "cycleCount": int(b.cycle),
                  "voltage": b.bmsvoltage[0] * BMS_V_SCALE, "current": b.current * BMS_I_SCALE,
                  "cellVoltages": [v * BMS_V_SCALE for v in b.cell_vol[:N_CELLS]],
                  "temperatures": [float(t) for t in b.temperature[:N_TEMPS]]}
            feats["battery"] = {"properties": {"status": st}}
            cv, tp = st["cellVoltages"], st["temperatures"]  # raw is scalar-only: arrays flattened for InfluxDB
            raw = {"ts": time.time_ns() // 1000, "soc": b.soc, "soh": b.soh, "cycleCount": int(b.cycle),
                   "voltage": st["voltage"], "current": st["current"], "cellVoltageMin": min(cv), "cellVoltageMax": max(cv)}
            raw.update({f"temperature{i}": t for i, t in enumerate(tp)})
            self._pub(f"phm/raw/{self.a.thing}/battery", json.dumps({"samples": [raw]}))
        if mode is not None:
            feats["controller"] = {"properties": {"status": {"mode": f"mode_machine={mode}"}}}
        ns, name = self.a.thing.split(":")
        self._pub(f"phm/state/{self.a.thing}", json.dumps({
            "topic": f"{ns}/{name}/things/twin/commands/merge",
            "headers": {"content-type": "application/merge-patch+json", "response-required": False},
            "path": "/features", "value": feats}))

    def run(self):
        ChannelFactoryInitialize(self.a.domain, self.a.iface)
        subs = [(ChannelSubscriber("rt/lowstate", LowState_), self.on_lowstate),
                (ChannelSubscriber("rt/lf/bmsstate", BmsState_), self.on_bms),
                (ChannelSubscriber("rt/lf/mainboardstate", MainBoardState_), self.on_board)]
        for sub, cb in subs:
            sub.Init(cb, 10)
        t0 = last_stat = time.time()
        next_state = t0
        n_prev = lost_prev = 0
        while self.a.duration is None or time.time() - t0 < self.a.duration:
            time.sleep(self.a.raw_batch_ms / 1000)
            self.flush_raw()
            now = time.time()
            if now >= next_state:
                self.publish_state()
                next_state = now + 1 / self.a.state_hz
            if now - last_stat >= 10:
                with self.lock:
                    n, lost = self.n_msgs, self.n_lost
                dt = now - last_stat
                print(f"[stats] lowstate {(n - n_prev) / dt:.0f} Hz, lost {lost - lost_prev} "
                      f"of {n - n_prev + lost - lost_prev} ({100 * (lost - lost_prev) / max(1, n - n_prev + lost - lost_prev):.2f}%), "
                      f"bms={'yes' if self.bms else 'no'} board={'yes' if self.board else 'no'}", flush=True)
                n_prev, lost_prev, last_stat = n, lost, now
                if self.a.dry_run and self.bms and self.board:
                    print("[bms]", self.bms.soc, self.bms.soh, self.bms.cycle, self.bms.current,
                          list(self.bms.bmsvoltage), list(self.bms.cell_vol[:N_CELLS]), list(self.bms.temperature[:N_TEMPS]))
                    print("[board]", list(self.board.temperature), list(self.board.value))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--iface", default=None, help="network interface facing the robot, e.g. enp6s0")
    p.add_argument("--domain", type=int, default=0)
    p.add_argument("--thing", default="lab.robots:g1-001")
    p.add_argument("--mqtt-host", default="127.0.0.1")
    p.add_argument("--mqtt-port", type=int, default=11883)
    p.add_argument("--mqtt-user", default="edge")
    p.add_argument("--raw-batch-ms", type=int, default=200)
    p.add_argument("--state-hz", type=float, default=5)
    p.add_argument("--duration", type=float, default=None, help="seconds; default run forever")
    p.add_argument("--dry-run", action="store_true", help="print instead of publishing to MQTT")
    Adapter(p.parse_args()).run()
