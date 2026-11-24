#!/usr/bin/env python3
"""Franka Panda / FR3 libfranka RobotState -> MQTT adapter. Read-only: never sends a motion or control command.

Robot::read_once() loop (~1 kHz) -> phm/raw/<thing>/joint1..7   batched samples (InfluxDB via Telegraf)
                                 -> phm/state/<thing>            Ditto merge patch at --state-hz
Backends: --backend pylibfranka (FR3, system >= 5, libfranka >= 0.15), panda_py (Panda, system 4.x,
libfranka 0.9.x build of panda-py), sim (MuJoCo Menagerie franka_emika_panda via mujoco_sim.py),
fake (synthetic RobotState without dependencies, for offline end-to-end tests).
Topic/payload contract: stack/README.md. FCI must be activated in Desk; only one FCI client at a time.
"""
import argparse, json, math, os, threading, time
from types import SimpleNamespace

JOINTS = [f"joint{i}" for i in range(1, 8)]  # MuJoCo Menagerie franka_emika_panda joint names


def open_robot(a):
    """Return an object with read_once() -> RobotState, plus a version string for the log."""
    if a.backend == "fake":
        return FakeRobot(a.fake_drop), "fake"
    if a.backend == "sim":
        return SimRobot(a), "sim"
    if a.backend == "pylibfranka":
        import pylibfranka as lf
    else:
        from panda_py import libfranka as lf
    try:
        r = lf.Robot(a.robot_ip, lf.RealtimeConfig.kIgnore)  # read-only: a non-RT kernel is acceptable
    except Exception as e:  # IncompatibleVersionException names the robot's server version
        raise SystemExit(f"cannot connect to {a.robot_ip} with {a.backend}: {e}\n"
                         "Server version 4 / system 4.x -> --backend panda_py (libfranka 0.9.x); "
                         "system >= 5 (FR3) -> --backend pylibfranka")
    ver = getattr(r, "server_version", None)  # panda-py binds it, pylibfranka does not
    return r, str(ver()) if callable(ver) else "n/a"


def to_ms(t):
    """RobotState.time is a franka::Duration; binding method names differ between backends."""
    for name in ("to_msec", "toMSec"):
        f = getattr(t, name, None)
        if f is not None:
            return int(f())
    for name in ("to_sec", "toSec"):
        f = getattr(t, name, None)
        if f is not None:
            return int(round(f() * 1000))
    return int(round(float(t) * 1000))


def active_errors(e):
    """Names of the franka::Errors flags that are set (both bindings expose one bool attribute per flag)."""
    return sorted(n for n in dir(e) if not n.startswith("_") and getattr(e, n, None) is True)


def mode_name(m):
    """RobotMode: pylibfranka names it Idle, panda-py kIdle; publish the libfranka C++ spelling (kIdle)."""
    n = str(getattr(m, "name", m)).split(".")[-1]
    return n if n[:1] == "k" and n[1:2].isupper() else "k" + n


class FakeRobot:
    """Synthetic RobotState at ~1 kHz with an optional packet-drop rate, for testing without hardware."""
    ERR_FIELDS = ("joint_position_limits_violation", "cartesian_reflex", "joint_reflex")

    def __init__(self, drop):
        self.ms, self.drop, self.next_t = 0, drop, time.monotonic()

    def read_once(self):
        self.next_t += 0.001
        time.sleep(max(0.0, self.next_t - time.monotonic()))
        self.ms += 1
        if self.drop and (self.ms * 2654435761) % 1000 < self.drop * 1000:
            self.ms += 1  # simulate one lost UDP state packet
        t = self.ms / 1000
        q = [0.3 * math.sin(0.5 * t + i) for i in range(7)]
        dq = [0.15 * math.cos(0.5 * t + i) for i in range(7)]
        tau_ext = [0.2 * math.sin(3 * t + i) for i in range(7)]
        errs = SimpleNamespace(**{f: False for f in self.ERR_FIELDS})
        return SimpleNamespace(
            time=SimpleNamespace(to_msec=lambda ms=self.ms: ms), q=q, dq=dq,
            tau_J=[5 * math.sin(0.5 * t + i) + tau_ext[i] for i in range(7)],
            theta=[x + 1e-4 * math.sin(t) for x in q], tau_ext_hat_filtered=tau_ext,
            joint_collision=[0.0] * 7, joint_contact=[0.0] * 7, current_errors=errs,
            robot_mode=SimpleNamespace(name="Idle"), control_command_success_rate=0.0)


class SimRobot:
    """Menagerie franka_emika_panda physics at 1 kHz, returned in RobotState shape (no temperatures, like FCI)."""
    TAU_RATED = (87,) * 4 + (12,) * 3  # Panda joint torque limits [N*m]
    K_JOINT = 2.0e4                    # transmission stiffness [N*m/rad]: theta - q = tau_J / K

    def __init__(self, a):
        from mujoco_sim import ArmSim, parse_wear
        self.sim = ArmSim(os.path.join(a.menagerie, "franka_emika_panda", "panda.xml"), JOINTS, self.TAU_RATED,
                          wear=parse_wear(a.sim_wear))
        self.ms, self.next_t = 0, time.monotonic()
        self.errs = SimpleNamespace(**{f: False for f in FakeRobot.ERR_FIELDS})

    def read_once(self):
        self.next_t += 0.001
        time.sleep(max(0.0, self.next_t - time.monotonic()))
        self.next_t = max(self.next_t, time.monotonic() - 0.05)  # do not burst after a stall
        s = self.sim
        s.step(0.001)
        self.ms += 1
        q, tau = s.q(), s.tau()
        return SimpleNamespace(
            time=SimpleNamespace(to_msec=lambda ms=self.ms: ms), q=q, dq=s.dq(), tau_J=tau,
            theta=q + tau / self.K_JOINT, tau_ext_hat_filtered=s.rng.normal(0, 0.05, 7),
            joint_collision=[0.0] * 7, joint_contact=[0.0] * 7, current_errors=self.errs,
            robot_mode=SimpleNamespace(name="Move"), control_command_success_rate=0.0)


class Adapter:
    def __init__(self, a):
        self.a, self.lock = a, threading.Lock()
        self.raw = [[] for _ in JOINTS]      # pending raw samples per joint
        self.latest = None                   # (per-joint tuples, mode, error names)
        self.n_msgs, self.n_lost, self.n_dup, self.last_ms = 0, 0, 0, None
        self.error = None                    # exception that stopped the reader thread
        self.stop = False
        self.mqtt = None if a.dry_run else self._mqtt()

    def _mqtt(self):
        import paho.mqtt.client as mqtt
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"panda-adapter-{os.getpid()}")
        except AttributeError:  # paho-mqtt 1.x
            c = mqtt.Client(client_id=f"panda-adapter-{os.getpid()}")
        c.username_pw_set(self.a.mqtt_user, os.environ["MQTT_EDGE_PASSWORD"])
        c.connect(self.a.mqtt_host, self.a.mqtt_port, keepalive=30)
        c.loop_start()
        return c

    # --- reader thread: one RobotState per control cycle (1 ms) ---
    def on_state(self, s):
        ts = time.time_ns() // 1000
        ms = to_ms(s.time)
        errs = active_errors(s.current_errors)
        any_err = 4 if errs else 0
        joints = []
        for i in range(7):
            # faultCode bits: 0 joint_collision, 1 joint_contact, 2 any robot-wide current error
            fault = (1 if s.joint_collision[i] else 0) | (2 if s.joint_contact[i] else 0) | any_err
            joints.append((float(s.q[i]), float(s.dq[i]), float(s.tau_J[i]), float(s.theta[i]),
                           float(s.tau_ext_hat_filtered[i]), fault))
        with self.lock:
            if self.last_ms is not None:
                if ms > self.last_ms:
                    self.n_lost += ms - self.last_ms - 1  # robot time advances 1 ms per state packet
                else:
                    self.n_dup += 1
                    return
            self.last_ms = ms
            self.n_msgs += 1
            for buf, (q, dq, tau, th, ext, fault) in zip(self.raw, joints):
                buf.append({"ts": ts, "position": q, "velocity": dq, "torque": tau,
                            "motorPosition": th, "externalTorque": ext, "faultCode": fault})
            self.latest = (joints, mode_name(s.robot_mode), errs)

    def reader(self, robot):
        try:
            while not self.stop:
                self.on_state(robot.read_once())
        except Exception as e:  # network loss, robot reboot, FCI deactivated
            self.error = e

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
            snap = self.latest
        if snap is None:
            return
        joints, mode, errs = snap
        feats = {name: {"properties": {"status": {
            "position": q, "velocity": dq, "torque": tau, "motorPosition": th,
            "externalTorque": ext, "faultCode": fault}}}
            for name, (q, dq, tau, th, ext, fault) in zip(JOINTS, joints)}
        feats["controller"] = {"properties": {"status": {"mode": mode, "faultCodes": errs}}}
        ns, name = self.a.thing.split(":")
        self._pub(f"phm/state/{self.a.thing}", json.dumps({
            "topic": f"{ns}/{name}/things/twin/commands/merge",
            "headers": {"content-type": "application/merge-patch+json", "response-required": False},
            "path": "/features", "value": feats}))

    def run(self):
        robot, ver = open_robot(self.a)
        print(f"[info] backend={self.a.backend} robot={self.a.robot_ip} server_version={ver}", flush=True)
        th = threading.Thread(target=self.reader, args=(robot,), daemon=True)
        th.start()
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
                    n, lost, dup = self.n_msgs, self.n_lost, self.n_dup
                dn, dl, dt = n - n_prev, lost - lost_prev, now - last_stat
                print(f"[stats] state {dn / dt:.0f} Hz, lost {dl} of {dn + dl} "
                      f"({100 * dl / max(1, dn + dl):.2f}%), dup total {dup}", flush=True)
                n_prev, lost_prev, last_stat = n, lost, now
            if self.error is not None:
                self.flush_raw()
                raise SystemExit(f"reader stopped: {self.error!r}")  # systemd restarts the adapter
        self.stop = True
        th.join(1)  # the sim backend must not step MuJoCo while the interpreter shuts down
        self.flush_raw()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--backend", choices=("pylibfranka", "panda_py", "sim", "fake"), default="pylibfranka")
    p.add_argument("--robot-ip", default="172.16.0.2", help="Franka control unit (FCI) address")
    p.add_argument("--thing", default="lab.robots:panda-001")
    p.add_argument("--mqtt-host", default="127.0.0.1")
    p.add_argument("--mqtt-port", type=int, default=11883)
    p.add_argument("--mqtt-user", default="edge")
    p.add_argument("--raw-batch-ms", type=int, default=200)
    p.add_argument("--state-hz", type=float, default=5)
    p.add_argument("--duration", type=float, default=None, help="seconds; default run forever")
    p.add_argument("--menagerie", default=os.environ.get("MENAGERIE_DIR", os.path.expanduser("~/mujoco_menagerie")),
                   help="sim backend: mujoco_menagerie checkout")
    p.add_argument("--sim-wear", nargs="*", metavar="JOINT=RATE",
                   help="sim backend: added damping and friction per hour, e.g. joint4=2")
    p.add_argument("--fake-drop", type=float, default=0.0, help="fake backend: packet drop ratio")
    p.add_argument("--dry-run", action="store_true", help="print instead of publishing to MQTT")
    Adapter(p.parse_args()).run()
