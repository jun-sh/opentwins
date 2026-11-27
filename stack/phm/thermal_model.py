"""First-order lumped thermal model of a joint actuator as a ProgPy PrognosticsModel.

    dT/dt = (t_amb + k * load - T) / tau,   load = torque^2 [(N.m)^2]
    event 'overheat' when T >= t_max (configuration.maxTemperature)
    event_state = thermal margin (t_max - T) / (t_max - t_ref), t_ref = 25 degC nominal ambient

Parameters (tau, k, t_amb) are fitted per joint with ProgPy's estimate_params on recent history;
time-to-threshold comes from ProgPy's simulate_to_threshold under the recent mean load.
"""
import math

from progpy import PrognosticsModel

BOUNDS = {"tau": (60.0, 7200.0), "k": (0.0, 50.0), "t_amb": (0.0, 60.0)}


class JointThermal(PrognosticsModel):
    inputs = ["load"]
    states = ["t"]
    outputs = ["t"]
    events = ["overheat"]
    default_parameters = {"x0": {"t": 30.0}, "tau": 900.0, "k": 0.05, "t_amb": 28.0, "t_max": 80.0, "t_ref": 25.0}

    def dx(self, x, u):
        p = self.parameters
        return self.StateContainer({"t": (p["t_amb"] + p["k"] * u["load"] - x["t"]) / p["tau"]})

    def output(self, x):
        return self.OutputContainer({"t": x["t"]})

    def event_state(self, x):
        p = self.parameters
        span = max(p["t_max"] - p["t_ref"], 1.0)  # fixed reference, not the fitted ambient
        return {"overheat": min(1.0, max(0.0, (p["t_max"] - x["t"]) / span))}

    def threshold_met(self, x):
        return {"overheat": x["t"] >= self.parameters["t_max"]}


def fit(model, times, temps, loads):
    """Fit tau, k, t_amb on one history segment; keeps defaults if the data is too short or flat."""
    if len(times) < 20 or max(temps) - min(temps) < 1.0:
        return False
    t0 = times[0]
    model.parameters["x0"] = {"t": temps[0]}
    try:
        model.estimate_params(
            times=[[t - t0 for t in times]],
            inputs=[[{"load": l} for l in loads]],
            outputs=[[{"t": t} for t in temps]],
            keys=list(BOUNDS), bounds=BOUNDS, dt=30.0,
            options={"maxiter": 200},
        )
    except Exception as e:  # noqa: BLE001 - a failed fit must not stop the assessment
        print(f"[thermal] fit failed: {e}")
        return False
    return True


def time_to_overheat_h(model, t_now, load, horizon_h):
    """Hours until T reaches t_max at constant load; horizon_h if it never does within the horizon."""
    p = model.parameters
    if t_now >= p["t_max"]:
        return 0.0
    if p["t_amb"] + p["k"] * load < p["t_max"]:  # steady state below the limit: no threshold event
        return float(horizon_h)
    res = model.simulate_to_threshold(
        lambda t, x=None: model.InputContainer({"load": load}),
        x={"t": t_now}, events=["overheat"], horizon=horizon_h * 3600.0,
        dt=min(60.0, p["tau"] / 10.0), save_freq=horizon_h * 3600.0,
    )
    t_end = res.times[-1]
    return min(float(horizon_h), t_end / 3600.0) if math.isfinite(t_end) else float(horizon_h)
