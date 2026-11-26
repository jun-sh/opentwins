"""MuJoCo arm simulator for the adapters' `--backend sim` (MuJoCo Menagerie MJCF, wall-clock real time).

Joints follow a smooth periodic trajectory under the model's own position servos, so velocities and
torques come from real rigid-body dynamics (gravity, inertia, damping). On top: a first-order thermal
model per joint (winding and driver heat from torque^2), measurement noise, and optional wear
injection (`wear={"joint3": 2.0}` adds that much damping and friction loss per hour) so the PHM pipeline has
something to detect. Wear hours count from process start, or with `wear_cycle_h` from the last multiple of
that period on the wall clock (UTC), so a restart keeps the wear and each cycle ends in a 'repair'. Only the adapter's SDK-shaped wrappers call this module.
"""
import math
import time

import mujoco
import numpy as np

DT = 0.001  # physics step [s]


class ArmSim:
    def __init__(self, mjcf, joints, tau_rated, wear=None, wear_cycle_h=0.0, seed=0, t_amb=25.0,
                 rise_w=60.0, rise_d=35.0, tc_w=300.0, tc_d=900.0):
        m = self.m = mujoco.MjModel.from_xml_path(mjcf)
        m.opt.timestep = DT
        m.body_gravcomp[:] = 0  # the drives carry gravity, as on the real arm (Menagerie PiPER compensates it)
        d = self.d = mujoco.MjData(m)
        if m.nkey:
            mujoco.mj_resetDataKeyframe(m, d, 0)  # Menagerie 'home' pose and servo targets
        jid = [m.joint(n).id for n in joints]
        self.dof = np.array([m.jnt_dofadr[j] for j in jid])
        self.qadr = np.array([m.jnt_qposadr[j] for j in jid])
        self.act = np.array([next(a for a in range(m.nu) if m.actuator_trntype[a] == mujoco.mjtTrn.mjTRN_JOINT
                                  and m.actuator_trnid[a][0] == j) for j in jid])
        lo, hi = m.jnt_range[jid].T
        home = d.qpos[self.qadr].copy()
        span = np.minimum(home - lo, hi - home)  # stay inside the joint range around home
        self.home, self.amp = home, 0.6 * np.clip(span, 0.0, 0.8)
        rng = np.random.default_rng(seed)
        self.freq, self.phase = rng.uniform(0.04, 0.12, len(jid)), rng.uniform(0, 2 * math.pi, len(jid))
        self.base_damp = m.dof_damping[self.dof].copy()
        self.base_fric = m.dof_frictionloss[self.dof].copy()
        self.wear = {joints.index(k): v for k, v in (wear or {}).items()}
        self.wear_cycle_h = wear_cycle_h
        self.tau_rated = np.asarray(tau_rated, float)
        self.t_amb, self.rise_w, self.rise_d, self.tc_w, self.tc_d = t_amb, rise_w, rise_d, tc_w, tc_d
        self.temp_w = np.full(len(jid), t_amb + 5.0)
        self.temp_d = np.full(len(jid), t_amb + 3.0)
        self.rng, self.t = rng, 0.0

    def step(self, dt):
        """Advance the physics and the thermal state by dt seconds (multiple of DT)."""
        m, d = self.m, self.d
        hours = (time.time() / 3600) % self.wear_cycle_h if self.wear_cycle_h > 0 else self.t / 3600
        for i, rate in self.wear.items():
            m.dof_damping[self.dof[i]] = self.base_damp[i] + rate * hours
            m.dof_frictionloss[self.dof[i]] = self.base_fric[i] + rate * hours
        n = max(1, round(dt / DT))
        for _ in range(n):
            self.t += DT
            # slow sinusoids with a pause around each turning point, like a pick-and-place cycle
            s = np.sin(2 * math.pi * self.freq * self.t + self.phase)
            ramp = min(1.0, self.t / 10)  # start from home without a step in the servo target
            d.ctrl[self.act] = self.home + ramp * self.amp * np.clip(1.25 * s, -1, 1)
            mujoco.mj_step(m, d)
        load = (self.tau() / self.tau_rated) ** 2
        a_w, a_d = 1 - math.exp(-n * DT / self.tc_w), 1 - math.exp(-n * DT / self.tc_d)
        self.temp_w += a_w * (self.t_amb + self.rise_w * load - self.temp_w)
        self.temp_d += a_d * (self.t_amb + self.rise_d * load - self.temp_d)

    def q(self):
        return self.d.qpos[self.qadr] + self.rng.normal(0, 2e-5, len(self.qadr))

    def dq(self):
        return self.d.qvel[self.dof] + self.rng.normal(0, 2e-4, len(self.dof))

    def tau(self):
        """Joint torque the drive delivers (servo force on the joint), with sensor noise."""
        return self.d.qfrc_actuator[self.dof] + self.rng.normal(0, 0.003, len(self.dof)) * self.tau_rated

    def temps(self):
        """(winding, driver) temperatures [degC] with 0.1 degC sensor noise."""
        k = len(self.dof)
        return self.temp_w + self.rng.normal(0, 0.1, k), self.temp_d + self.rng.normal(0, 0.1, k)


def parse_wear(items):
    """['joint3=2.0', ...] -> {'joint3': 2.0}"""
    return {k: float(v) for k, v in (s.split("=", 1) for s in items or [])}
