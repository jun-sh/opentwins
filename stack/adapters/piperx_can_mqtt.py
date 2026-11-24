#!/usr/bin/env python3
"""AgileX PiPER / PiPER X piper_sdk (CAN) -> MQTT adapter. Read-only: never sends enable, mode or motion frames.

piper_sdk feedback cache, polled at --poll-hz -> phm/raw/<thing>/joint1..6   batched samples (InfluxDB via Telegraf)
                                               -> phm/state/<thing>           Ditto merge patch at --state-hz
Backends: --backend sdk (piper_sdk on a SocketCAN port; firmware >= 1.8-8 uses C_PiperInterface_V3, older V2),
sim (MuJoCo Menagerie agilex_piper via mujoco_sim.py), fake (synthetic feedback without dependencies). Topic/payload contract: stack/README.md.
Joint feedback only flows while the arm is in slave mode (piper_sdk README); this adapter never changes that.
"""
import argparse, json, math, os, threading, time

import numpy as np
from types import SimpleNamespace as NS

JOINTS = [f"joint{i}" for i in range(1, 7)]  # MuJoCo Menagerie agilex_piper joint names
# foc_status bool flags (piper_sdk low-speed feedback) -> faultCode bit index
FOC_BITS = ("voltage_too_low", "motor_overheating", "driver_overcurrent", "driver_overheating",
            "collision_status", "driver_error_status", "driver_enable_status", "stall_status")
CTRL_MODE = {0: "standby", 1: "can_control", 2: "teaching"}
ARM_STATUS = {0x00: "normal", 0x01: "emergency_stop", 0x02: "no_solution", 0x03: "singularity",
              0x04: "target_angle_over_limit", 0x05: "joint_comm_abnormal", 0x06: "brake_not_open",
              0x07: "collision", 0x08: "drag_teach_overspeed", 0x09: "joint_abnormal", 0x0A: "other",
              0x0E: "controller_ntc_overtemp", 0x0F: "release_resistor_ntc_overtemp"}
DEG_MILLI = math.pi / 180 / 1000  # 0.001 deg -> rad


def open_piper(a):
    """Return (piper, firmware string). piper exposes the piper_sdk Get* feedback methods."""
    if a.backend == "fake":
        return FakePiper(), "fake"
    if a.backend == "sim":
        return SimPiper(a), "sim"
    import piper_sdk
    cls = getattr(piper_sdk, f"C_PiperInterface_{a.sdk_version}")
    p = cls(can_name=a.can)
    p.ConnectPort()  # piper_init only queries limits and firmware; no enable/motion frame is sent
    time.sleep(0.05)  # firmware reply needs ~25 ms after connect (piper_sdk README)
    fw = p.GetPiperFirmwareVersion()
    return p, str(fw)


def foc_word(foc):
    """faultCode: set foc_status flags; bit 6 (driver enabled) is a state, not a fault, so it stays 0."""
    return sum(1 << i for i, n in enumerate(FOC_BITS) if n != "driver_enable_status" and getattr(foc, n, False))


def status_names(st):
    """Controller fault strings: non-normal arm_status plus set err_status flags."""
    s = st.arm_status
    names = [] if s.arm_status == 0 else [ARM_STATUS.get(int(s.arm_status), f"arm_status_0x{int(s.arm_status):02x}")]
    err = getattr(s, "err_status", None)
    if err is not None:
        names += sorted(n for n in dir(err) if not n.startswith("_") and getattr(err, n, None) is True)
    return names


class FakePiper:
    """Synthetic feedback with SDK-like shapes and units; one new high-speed frame per poll."""

    def __init__(self):
        self.t0 = time.time()

    def _t(self):
        return time.time() - self.t0

    def GetArmJointMsgs(self):
        t = self._t()
        js = NS(**{f"joint_{i}": int(30000 * math.sin(0.4 * t + i)) for i in range(1, 7)})  # 0.001 deg
        return NS(time_stamp=time.time(), Hz=200.0, joint_state=js)

    def GetArmHighSpdInfoMsgs(self):
        t = self._t()
        m = {f"motor_{i}": NS(motor_speed=int(200 * math.cos(0.4 * t + i)), current=int(800 + 300 * math.sin(t + i)),
                              effort=int(1500 * math.sin(0.4 * t + i)), pos=0) for i in range(1, 7)}
        return NS(time_stamp=time.time(), Hz=200.0, **m)

    def GetArmLowSpdInfoMsgs(self):
        t = self._t()
        m = {f"motor_{i}": NS(vol=240, motor_temp=35 + i + int(t / 60), foc_temp=30 + i,
                              bus_current=500, foc_status=NS(**{n: n == "driver_enable_status" for n in FOC_BITS}))
             for i in range(1, 7)}
        return NS(time_stamp=time.time(), Hz=20.0, **m)

    def GetArmStatus(self):
        err = NS(**{f"joint_{i}_angle_limit": False for i in range(1, 7)})
        return NS(time_stamp=time.time(), Hz=200.0,
                  arm_status=NS(ctrl_mode=0, arm_status=0, err_status=err))


class SimPiper:
    """Menagerie agilex_piper physics behind the piper_sdk getters: one high-speed frame per 5 ms of wall time."""
    TAU_RATED = (10, 10, 10, 3, 3, 3)  # assumed rated joint torques [N*m]; not published by AgileX
    FRAME = 0.005

    def __init__(self, a):
        from mujoco_sim import ArmSim, parse_wear
        self.sim = ArmSim(os.path.join(a.menagerie, "agilex_piper", "piper.xml"), JOINTS, self.TAU_RATED,
                          wear=parse_wear(a.sim_wear))
        self.t_sim, self.f = time.time(), None
        self._sync()

    def _sync(self):
        now = time.time()
        n = int((now - self.t_sim) / self.FRAME)
        if n == 0 and self.f is not None:
            return
        n = min(max(n, 1), 20)  # after a stall, catch up at most 100 ms of physics
        self.sim.step(n * self.FRAME)
        self.t_sim = max(self.t_sim + n * self.FRAME, now - 0.1)
        s = self.sim
        tau = s.tau()
        amps = 0.15 + abs(tau) / (np.array(self.TAU_RATED) / 3)  # ~3 A at rated torque
        self.f = NS(ts=now, q=s.q(), dq=s.dq(), tau=tau, amps=amps, temps=s.temps(), vol=24.0 - 0.05 * amps.sum())

    def GetArmJointMsgs(self):
        self._sync()
        f = self.f
        return NS(time_stamp=f.ts, Hz=200.0, joint_state=NS(**{f"joint_{i + 1}": int(round(math.degrees(v) * 1000))
                                                              for i, v in enumerate(f.q)}))

    def GetArmHighSpdInfoMsgs(self):
        self._sync()
        f = self.f
        m = {f"motor_{i + 1}": NS(motor_speed=int(f.dq[i] * 1000), current=int(f.amps[i] * 1000),
                                  effort=int(f.tau[i] * 1000), pos=0) for i in range(6)}
        return NS(time_stamp=f.ts, Hz=200.0, **m)

    def GetArmLowSpdInfoMsgs(self):
        self._sync()
        f, (tw, td) = self.f, self.f.temps
        m = {f"motor_{i + 1}": NS(vol=int(round(f.vol * 10)), motor_temp=int(tw[i]), foc_temp=int(td[i]),
                                  bus_current=int(f.amps.sum() * 1000),
                                  foc_status=NS(**{n: n == "driver_enable_status" or (n == "motor_overheating" and tw[i] > 70)
                                                   for n in FOC_BITS})) for i in range(6)}
        return NS(time_stamp=f.ts, Hz=20.0, **m)

    def GetArmStatus(self):
        err = NS(**{f"joint_{i}_angle_limit": False for i in range(1, 7)})
        return NS(time_stamp=self.f.ts, Hz=200.0, arm_status=NS(ctrl_mode=1, arm_status=0, err_status=err))


class Adapter:
    def __init__(self, a):
        self.a, self.lock = a, threading.Lock()
        self.raw = [[] for _ in JOINTS]
        self.latest = None
        self.n_new, self.n_polls, self.last_hs = 0, 0, None
        self.hz = {}
        self.mqtt = None if a.dry_run else self._mqtt()

    def _mqtt(self):
        import paho.mqtt.client as mqtt
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"piperx-adapter-{os.getpid()}")
        except AttributeError:  # paho-mqtt 1.x
            c = mqtt.Client(client_id=f"piperx-adapter-{os.getpid()}")
        c.username_pw_set(self.a.mqtt_user, os.environ["MQTT_EDGE_PASSWORD"])
        c.connect(self.a.mqtt_host, self.a.mqtt_port, keepalive=30)
        c.loop_start()
        return c

    def poll(self, p):
        """Sample the SDK cache; append a raw sample only when a new high-speed frame arrived."""
        js, hs, ls, st = p.GetArmJointMsgs(), p.GetArmHighSpdInfoMsgs(), p.GetArmLowSpdInfoMsgs(), p.GetArmStatus()
        with self.lock:
            self.n_polls += 1
            self.hz = {"joint": js.Hz, "high": hs.Hz, "low": ls.Hz}
            if hs.time_stamp == self.last_hs:
                return
            self.last_hs = hs.time_stamp
            self.n_new += 1
        ts = time.time_ns() // 1000
        joints = []
        for i in range(1, 7):
            h, l = getattr(hs, f"motor_{i}"), getattr(ls, f"motor_{i}")
            joints.append({"position": getattr(js.joint_state, f"joint_{i}") * DEG_MILLI,
                           "velocity": h.motor_speed / 1000, "torque": h.effort / 1000, "current": h.current / 1000,
                           "busVoltage": l.vol / 10, "windingTemperature": float(l.motor_temp),
                           "driverTemperature": float(l.foc_temp), "faultCode": foc_word(l.foc_status)})
        s = st.arm_status
        ctrl = {"mode": f"{CTRL_MODE.get(int(s.ctrl_mode), int(s.ctrl_mode))}/"
                        f"{ARM_STATUS.get(int(s.arm_status), hex(int(s.arm_status)))}",
                "faultCodes": status_names(st)}
        with self.lock:
            for buf, j in zip(self.raw, joints):
                buf.append({"ts": ts, **j})
            self.latest = (joints, ctrl)

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

    def publish_state(self, firmware):
        with self.lock:
            snap = self.latest
        if snap is None:
            return
        joints, ctrl = snap
        feats = {n: {"properties": {"status": j}} for n, j in zip(JOINTS, joints)}
        feats["controller"] = {"properties": {"status": ctrl}}
        if firmware and firmware not in ("-", "fake", "sim"):
            feats["controller"]["properties"]["configuration"] = {"firmwareVersion": firmware}
        ns, name = self.a.thing.split(":")
        self._pub(f"phm/state/{self.a.thing}", json.dumps({
            "topic": f"{ns}/{name}/things/twin/commands/merge",
            "headers": {"content-type": "application/merge-patch+json", "response-required": False},
            "path": "/features", "value": feats}))

    def run(self):
        piper, fw = open_piper(self.a)
        print(f"[info] backend={self.a.backend} can={self.a.can} firmware={fw}", flush=True)
        period = 1 / self.a.poll_hz
        t0 = last_flush = last_stat = time.time()
        next_poll, next_state = t0, t0
        new_prev = polls_prev = 0
        while self.a.duration is None or time.time() - t0 < self.a.duration:
            next_poll += period
            time.sleep(max(0.0, next_poll - time.time()))
            self.poll(piper)
            now = time.time()
            if now - last_flush >= self.a.raw_batch_ms / 1000:
                self.flush_raw()
                last_flush = now
            if now >= next_state:
                self.publish_state(fw)
                next_state = now + 1 / self.a.state_hz
            if now - last_stat >= 10:
                with self.lock:
                    n, polls, hz = self.n_new, self.n_polls, dict(self.hz)
                dt = now - last_stat
                print(f"[stats] new frames {(n - new_prev) / dt:.0f} Hz from {(polls - polls_prev) / dt:.0f} Hz polls; "
                      f"sdk fps joint={hz.get('joint', 0):.0f} high={hz.get('high', 0):.0f} low={hz.get('low', 0):.0f}",
                      flush=True)
                new_prev, polls_prev, last_stat = n, polls, now
        self.flush_raw()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", choices=("sdk", "sim", "fake"), default="sdk")
    ap.add_argument("--can", default="can0", help="SocketCAN interface of the arm")
    ap.add_argument("--sdk-version", choices=("V2", "V3"), default="V3", help="V3 for firmware >= 1.8-8")
    ap.add_argument("--thing", default="lab.robots:piperx-001")
    ap.add_argument("--mqtt-host", default="127.0.0.1")
    ap.add_argument("--mqtt-port", type=int, default=11883)
    ap.add_argument("--mqtt-user", default="edge")
    ap.add_argument("--poll-hz", type=float, default=200, help="SDK cache poll rate; >= feedback rate")
    ap.add_argument("--raw-batch-ms", type=int, default=200)
    ap.add_argument("--state-hz", type=float, default=5)
    ap.add_argument("--duration", type=float, default=None, help="seconds; default run forever")
    ap.add_argument("--menagerie", default=os.environ.get("MENAGERIE_DIR", os.path.expanduser("~/mujoco_menagerie")),
                    help="sim backend: mujoco_menagerie checkout")
    ap.add_argument("--sim-wear", nargs="*", metavar="JOINT=RATE",
                    help="sim backend: added damping and friction per hour, e.g. joint2=2")
    ap.add_argument("--dry-run", action="store_true", help="print instead of publishing to MQTT")
    Adapter(ap.parse_args()).run()
