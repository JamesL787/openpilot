"""lat_score.py: metric definitions and the gate verdicts, on synthetic 100 Hz traces (no route data, no controller)."""
import numpy as np
import pytest

from openpilot.tools.lateral import lat_score as L

N = 60 * 100


def _route(v=6.5, des=None, ang=None):
  t = np.arange(N) / 100
  des = np.zeros(N) if des is None else des
  return {"t": t, "v": np.full(N, v) if np.isscalar(v) else v, "active": np.ones(N), "pressed": np.zeros(N),
          "lane_change": np.zeros(N), "des_angle": des, "angle": des.copy() if ang is None else ang}


def test_wobble_sees_1hz_not_drift():
  t = np.arange(N) / 100
  d = _route()
  osc = L.score_arrays(d, 0.5 * np.sin(2 * np.pi * 1.0 * t), d["des_angle"])["wobble5-8"]
  drift = L.score_arrays(d, 0.5 * np.sin(2 * np.pi * 0.05 * t), d["des_angle"])["wobble5-8"]
  assert osc > 0.25 and drift < 0.02
  assert L.score_arrays(d, d["angle"], d["des_angle"])["wobble8-12"] is None  # no frames in that bin


def test_turn_error_saturation_and_ffw_bins():
  des = np.full(N, 60.0)
  d = _route(v=5.0, des=des, ang=des - 10.0)
  out = np.where(np.arange(N) % 4 == 0, 1.0, 0.5)
  r = L.score_arrays(d, d["angle"], des, out=out, ffw=np.full(N, 0.7))
  assert r["turn_err<12mph"] == pytest.approx(10.0)
  assert r["turn_trail<12mph"] == pytest.approx(10.0) and r["turn_past<12mph"] == 0.0
  assert r["turn_sat<12mph"] == pytest.approx(0.25)
  assert r["turn_ffw<12mph"] == pytest.approx(0.7)
  assert r["turn_err12-25mph"] is None


def test_turn_error_split_is_signed_by_desired():
  des = np.full(N, -60.0)
  d = _route(v=5.0, des=des, ang=np.where(np.arange(N) % 2 == 0, -64.0, -58.0))  # past by 4, trailing by 2
  r = L.score_arrays(d, d["angle"], des)
  assert r["turn_past<12mph"] == pytest.approx(2.0) and r["turn_trail<12mph"] == pytest.approx(1.0)
  assert r["turn_trail<12mph"] + r["turn_past<12mph"] == pytest.approx(r["turn_err<12mph"])


def test_dither_ignores_resting_noise():
  d = _route(v=10.0)
  noise = 1e-3 * np.sign(np.sin(np.arange(N)))
  assert L.score_arrays(d, d["angle"], d["des_angle"], out=noise)["dither8-12"] == 0.0
  square = 0.05 * np.sign(np.sin(2 * np.pi * 1.0 * np.arange(N) / 100 + 0.1))  # 2 reversals per second
  assert L.score_arrays(d, d["angle"], d["des_angle"], out=square)["dither8-12"] == pytest.approx(2.0, abs=0.05)


def test_pullaway_counts_starts():
  v = np.where((np.arange(N) // 1500) % 2 == 0, 0.0, 3.0)  # two stops, two starts
  r = L.pullaway_wobble(_route(v=v), np.zeros(N), np.zeros(N))
  assert r["pullaway_n"] == 2 and r["pullaway_wobble"] == pytest.approx(0.0, abs=1e-9)


def _figs(base, cand, route="00000999--x"):
  return L.compare(base, cand, route)


def test_gate_tolerances():
  b = {"wobble5-8": 0.20, "turn_err<12mph": 15.0, "dither8-12": 1.0, "err_rms_low": 10.0}
  f = _figs(b, {"wobble5-8": 0.24, "turn_err<12mph": 15.4, "dither8-12": 1.09, "err_rms_low": 10.29})
  assert {f[k] for k in b} == {"same"}
  f = _figs(b, {"wobble5-8": 0.26, "turn_err<12mph": 15.6, "dither8-12": 1.2, "err_rms_low": 10.4})
  assert {f[k] for k in b} == {"regress"}
  f = _figs(b, {"wobble5-8": 0.14, "turn_err<12mph": 14.4, "dither8-12": 0.8, "err_rms_low": 9.6})
  assert {f[k] for k in b} == {"improve"}
  assert "wobble2-5" not in f  # re-synced to the log below 4 m/s: reported, not gated


def test_untrusted_figure_not_gated():
  f = L.compare({"turn_err<12mph": 10.0}, {"turn_err<12mph": 20.0}, "00000284--1109db7c4c")
  assert f["turn_err<12mph"] == "untrusted"


@pytest.mark.parametrize("states,want", [
  (["improve", "same"], "pass"), (["same", "same"], "neutral"), (["improve", "regress"], "mixed"),
  (["regress", "same"], "fail"),
])
def test_verdict(states, want):
  assert L.verdict({str(i): {"x": s} for i, s in enumerate(states)}) == want


def test_resolve_params_keeps_controllers_apart():
  logged = {"NrdrLatEpsFirmwareFF": "1", "NrdrLatPidFirmwareFF": "1"}
  assert L._toggles(L.resolve_params(logged, "pid", {})) == {"NrdrLatEpsFirmwareFF": "0", "NrdrLatPidFirmwareFF": "1"}
  assert L._toggles(L.resolve_params(logged, "clarity_eps", {})) == {"NrdrLatEpsFirmwareFF": "1", "NrdrLatPidFirmwareFF": "0"}
  assert L.resolve_params({}, "pid", {})["NrdrLatPidFirmwareFF"] == "0"
