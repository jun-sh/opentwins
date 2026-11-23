"""OPC UA simulator of a pump set (motor + drive-end/non-drive-end bearings + centrifugal pump).

Built on asyncua (FreeOpcUa, LGPL-3.0). Plays the role of a plant PLC/DCS: it only serves
engineering values; the mapping to the twin lives in telegraf-opcua.conf (config, not code).

Address space (namespace urn:opentwins:plant-sim, string NodeIds):
  PumpSet01.Motor.{Speed[rad/s], StatorCurrent[A], Torque[N.m], WindingTemperature[Cel], AlarmWord}
  PumpSet01.BearingDE.{VibrationRms[mm/s], VibrationPeak[mm/s], Temperature[Cel]}   (same for BearingNDE)
  PumpSet01.Pump.{Flow[m3/s], SuctionPressure[kPa], DischargePressure[kPa]}
  PumpSet01.Controller.Mode, PumpSet01.Alarms.<name> (Boolean)
  PumpSet01.Sim.{BearingWear, BearingWearRate[1/h], Running, AutoReplace}   writable = degradation injection

Degradation: drive-end bearing wear w in [0, 1] grows at BearingWearRate (per simulated hour);
vibration, bearing temperature and current rise with w. With AutoReplace, w resets to 0 at 1
(simulated bearing replacement), so the signal is a repeatable run-to-failure sawtooth.
Thresholds follow ISO 10816-3 group 1 (rigid foundation): 7.1 mm/s alarm, 11.2 mm/s trip.
"""
import argparse
import asyncio
import logging
import math
import os
import random

from asyncua import Server, ua

NS_URI = "urn:opentwins:plant-sim"
ROOT = "PumpSet01"

# Nameplate (illustrative 30 kW, 4-pole, 50 Hz process pump)
N0 = 1485 * 2 * math.pi / 60      # rad/s
I0 = 55.0                         # A at duty point
P0 = 30e3                         # W shaft power
Q0 = 500 / 3600                   # m3/s
P_SUCT, P_DIS = 250.0, 1200.0     # kPa
T_AMB = 35.0                      # Cel

ALARMS = [  # (name, bit, predicate on state dict)
    ("VibrationHigh", 0, lambda s: max(s["vde"], s["vnde"]) > 7.1),
    ("VibrationTrip", 1, lambda s: max(s["vde"], s["vnde"]) > 11.2),
    ("BearingTempHigh", 2, lambda s: max(s["tde"], s["tnde"]) > 85.0),
    ("WindingTempHigh", 3, lambda s: s["twind"] > 130.0),
    ("FlowLow", 4, lambda s: s["running"] and s["flow"] < 0.7 * Q0),
    ("MotorOvercurrent", 5, lambda s: s["cur"] > 1.15 * I0),
]


class PumpSet:
    """Lumped, deliberately simple physics: enough to show trends, not a design model."""

    def __init__(self, wear, rate, time_scale):
        self.wear, self.rate, self.time_scale = wear, rate, time_scale
        self.running, self.auto_replace = True, True
        self.speed = N0
        self.twind = T_AMB + 55.0 * (0.92 ** 2)
        self.tde, self.tnde = 45.0, 42.0
        self.replacements = 0

    def step(self, dt):
        sdt = dt * self.time_scale                       # simulated seconds
        if self.running:
            self.wear = min(1.0, self.wear + self.rate * sdt / 3600)
            if self.wear >= 1.0 and self.auto_replace:
                self.wear, self.replacements = 0.0, self.replacements + 1
                logging.info("bearing DE replaced (#%d)", self.replacements)
        w = self.wear
        target = N0 * (1 - 0.004 * w) if self.running else 0.0
        self.speed += (target - self.speed) * min(1.0, sdt / 5.0)   # ~5 s run-up / coast-down
        r = self.speed / N0
        load = r ** 3 * (0.92 + 0.08 * w)                # friction adds load as the bearing wears
        cur = (I0 * (0.30 + 0.70 * load) if r > 0.02 else 0.0) * (1 + random.gauss(0, 0.005))
        lag = lambda x, tgt, tau: x + (tgt - x) * min(1.0, sdt / tau)
        self.twind = lag(self.twind, T_AMB + 55.0 * (cur / I0) ** 2, 600.0)
        self.tde = lag(self.tde, T_AMB + r * (10.0 + 45.0 * w), 300.0)
        self.tnde = lag(self.tnde, T_AMB + r * (7.0 + 8.0 * w), 300.0)
        vde = r * (1.6 + 2.5 * w + 9.0 * w ** 3) * (1 + random.gauss(0, 0.03))
        vnde = r * (1.2 + 0.6 * w + 2.0 * w ** 3) * (1 + random.gauss(0, 0.03))
        flow = Q0 * r * (1 - 0.05 * w) * (1 + random.gauss(0, 0.01))
        return {
            "running": self.running, "speed": self.speed * (1 + random.gauss(0, 0.0005)), "cur": cur,
            "torque": P0 * load / self.speed if self.speed > 1 else 0.0, "twind": self.twind,
            "vde": vde, "vpde": vde * (1.41 + 2.0 * w) * (1 + abs(random.gauss(0, 0.05))),
            "vnde": vnde, "vpnde": vnde * 1.45 * (1 + abs(random.gauss(0, 0.05))),
            "tde": self.tde + random.gauss(0, 0.05), "tnde": self.tnde + random.gauss(0, 0.05),
            "flow": flow, "psuct": P_SUCT + random.gauss(0, 1.0),
            "pdis": P_SUCT + (P_DIS - P_SUCT) * r ** 2 * (1 - 0.03 * w) + random.gauss(0, 3.0),
        }


# (OPC UA path, state key or None for constant, initial value, variant type)
SIGNALS = [
    ("Motor.Speed", "speed", 0.0, ua.VariantType.Double),
    ("Motor.StatorCurrent", "cur", 0.0, ua.VariantType.Double),
    ("Motor.Torque", "torque", 0.0, ua.VariantType.Double),
    ("Motor.WindingTemperature", "twind", 0.0, ua.VariantType.Double),
    ("BearingDE.VibrationRms", "vde", 0.0, ua.VariantType.Double),
    ("BearingDE.VibrationPeak", "vpde", 0.0, ua.VariantType.Double),
    ("BearingDE.Temperature", "tde", 0.0, ua.VariantType.Double),
    ("BearingNDE.VibrationRms", "vnde", 0.0, ua.VariantType.Double),
    ("BearingNDE.VibrationPeak", "vpnde", 0.0, ua.VariantType.Double),
    ("BearingNDE.Temperature", "tnde", 0.0, ua.VariantType.Double),
    ("Pump.Flow", "flow", 0.0, ua.VariantType.Double),
    ("Pump.SuctionPressure", "psuct", 0.0, ua.VariantType.Double),
    ("Pump.DischargePressure", "pdis", 0.0, ua.VariantType.Double),
]


async def folder_tree(server, idx):
    """Create PumpSet01 and its sub-objects; returns {"Motor": node, ...}."""
    root = await server.nodes.objects.add_object(ua.NodeId(ROOT, idx), ua.QualifiedName(ROOT, idx))
    objs = {}
    for name in ("Motor", "BearingDE", "BearingNDE", "Pump", "Controller", "Alarms", "Sim"):
        objs[name] = await root.add_object(ua.NodeId(f"{ROOT}.{name}", idx), ua.QualifiedName(name, idx))
    return objs


async def add_var(objs, idx, path, value, vtype, writable=False):
    obj, name = path.split(".")
    node = await objs[obj].add_variable(ua.NodeId(f"{ROOT}.{path}", idx), ua.QualifiedName(name, idx),
                                        ua.Variant(value, vtype))
    if writable:
        await node.set_writable()
    return node


async def main(a):
    server = Server()
    await server.init()
    server.set_endpoint(a.endpoint)
    server.set_server_name("opentwins plant-sim pump set")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])   # lab demo; see README for hardening
    idx = await server.register_namespace(NS_URI)
    objs = await folder_tree(server, idx)

    sim = PumpSet(a.wear, a.wear_rate, a.time_scale)
    sig = [(await add_var(objs, idx, p, v, t), k, t) for p, k, v, t in SIGNALS]
    alarm_word = await add_var(objs, idx, "Motor.AlarmWord", 0, ua.VariantType.UInt32)
    mode = await add_var(objs, idx, "Controller.Mode", "Running", ua.VariantType.String)
    alarm_nodes = [(await add_var(objs, idx, f"Alarms.{n}", False, ua.VariantType.Boolean), b, f)
                   for n, b, f in ALARMS]
    w_wear = await add_var(objs, idx, "Sim.BearingWear", sim.wear, ua.VariantType.Double, True)
    w_rate = await add_var(objs, idx, "Sim.BearingWearRate", sim.rate, ua.VariantType.Double, True)
    w_run = await add_var(objs, idx, "Sim.Running", True, ua.VariantType.Boolean, True)
    w_repl = await add_var(objs, idx, "Sim.AutoReplace", True, ua.VariantType.Boolean, True)

    dt = 1.0 / a.rate
    logging.info("serving %s (ns=%d %s), wear=%.3f rate=%.3f/h, time scale x%g",
                 a.endpoint, idx, NS_URI, sim.wear, sim.rate, sim.time_scale)
    async with server:
        last_log, loop = 0.0, asyncio.get_running_loop()
        while True:
            t0 = loop.time()
            # Pick up operator/test writes (degradation injection) before stepping.
            sim.rate = max(0.0, float(await w_rate.read_value()))
            sim.running = bool(await w_run.read_value())
            sim.auto_replace = bool(await w_repl.read_value())
            wear_in = float(await w_wear.read_value())
            if abs(wear_in - sim.wear) > 1e-9:
                sim.wear = min(1.0, max(0.0, wear_in))
            s = sim.step(dt)
            for node, key, vtype in sig:
                await node.write_value(ua.Variant(float(s[key]), vtype))
            word = 0
            for node, bit, pred in alarm_nodes:
                on = bool(pred(s))
                word |= int(on) << bit
                await node.write_value(ua.Variant(on, ua.VariantType.Boolean))
            await alarm_word.write_value(ua.Variant(word, ua.VariantType.UInt32))
            await mode.write_value(ua.Variant("Running" if sim.running else "Stopped", ua.VariantType.String))
            await w_wear.write_value(ua.Variant(sim.wear, ua.VariantType.Double))
            if t0 - last_log >= 60:
                last_log = t0
                logging.info("wear=%.3f vibDE=%.2f mm/s tDE=%.1f C I=%.1f A alarms=0x%02x",
                             sim.wear, s["vde"], s["tde"], s["cur"], word)
            await asyncio.sleep(max(0.0, dt - (loop.time() - t0)))


if __name__ == "__main__":
    env = os.environ.get
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--endpoint", default=env("SIM_ENDPOINT", "opc.tcp://0.0.0.0:4840/plant-sim/"))
    p.add_argument("--rate", type=float, default=float(env("SIM_RATE_HZ", "10")), help="update rate, Hz")
    p.add_argument("--wear", type=float, default=float(env("SIM_BEARING_WEAR", "0")), help="initial wear 0..1")
    p.add_argument("--wear-rate", type=float, default=float(env("SIM_BEARING_WEAR_RATE", "0.5")),
                   help="wear per simulated hour")
    p.add_argument("--time-scale", type=float, default=float(env("SIM_TIME_SCALE", "1")),
                   help="simulated seconds per wall-clock second")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    asyncio.run(main(p.parse_args()))
