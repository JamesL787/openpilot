"""The HondaEps car learner (lib/honda_eps_car_learner.py) and its shadow daemon's plumbing, on synthetic drives."""
import dataclasses
import json
from types import SimpleNamespace

import numpy as np
import pytest

import openpilot.selfdrive.controls.honda_eps_learnerd as learnerd
import openpilot.selfdrive.controls.lib.honda_eps_calibrations as eps_cal
import openpilot.selfdrive.controls.lib.honda_eps_car_learner as L
import openpilot.selfdrive.controls.lib.honda_eps_firmware_ff as eps_ff
from opendbc.car.honda import steer_ratio as sr
from opendbc.car.honda.values import CAR
from opendbc.car.honda.yaw_rate import LEARN_FRAMES, SETTLE_FRAMES, yaw_rate_deg_s
from openpilot.selfdrive.controls.lib.honda_eps_column_plant import Plant
from openpilot.selfdrive.controls.lib.honda_eps_driver_yield import FRICTION_WIDTH
from openpilot.selfdrive.controls.lib.honda_eps_rack_map import HondaEpsRackMap
from openpilot.selfdrive.controls.tests.test_honda_eps_firmware_ff import _params

CAL = eps_cal.CRV_TLA_A040
WHEELBASE = 2.66
VGR = sr.HONDA_VGR_INVERSE_BY_PROFILE[sr.HONDA_VGR_CRV_TLA_A040]
YAW = (0.245, 509.5, 0.49)


def shipped_rack():
  assert CAL.rack is not None
  return CAL.rack


RACK = shipped_rack()
TRUE_LOAD = eps_ff.ColumnLoadModel(k0=-11.0, k1=-0.12, c=-6.0, friction=-360.0, bias=-30.0, kroll=-4.0)
N = int(L.CHUNK_S / L.DT)


def chunk(t0=0.0, n=N, angle=None, **fields):
  c: dict[str, object] = {k: np.zeros(n) for k in L.CHUNK_FIELDS}
  if angle is not None:
    fields['ang'] = angle
  c.update(t=t0 + np.arange(n) * L.DT, v=np.full(n, 12.0), lat=np.ones(n), eps_ok=np.ones(n), cmd_delay=np.full(n, 0.12), model=None, gps=None)
  c.update(fields)
  return c


def driven_chunk(i, v, amplitude, load=TRUE_LOAD):
  """A minute of the column plant following a wandering target under a crude P controller, as logged."""
  rng = np.random.default_rng(i)
  t = np.arange(N) * L.DT
  target = amplitude * (np.sin(2 * np.pi * t / rng.uniform(5, 9)) + 0.4 * np.sin(2 * np.pi * t / rng.uniform(1.2, 2.5) + 1.0))
  plant = Plant(dataclasses.replace(CAL, load=load), L.OL_J, 0.0)
  angle, e4 = np.zeros(N), np.zeros(N)
  th = 0.0
  for k in range(N):
    e4[k] = np.clip(np.round(-120.0 * (target[k] - th)), -3800, 3800)  # positive 0xE4 turns the wheel right
    th = angle[k] = plant.frame(e4[k - L.OL_CMD_LAG] if k >= L.OL_CMD_LAG else 0.0, v, 0.0)
  return chunk(i * 100.0, v=np.full(N, v), angle=angle, rate=np.gradient(angle, L.DT), e4=e4)


@pytest.fixture(scope="module")
def driven():
  return [driven_chunk(i, v, a) for i, (v, a) in enumerate([(4.0, 60.0), (7.0, 40.0), (12.0, 25.0), (12.0, 8.0), (18.0, 6.0), (18.0, 10.0),
                                                             (28.0, 3.0), (28.0, 5.0), (7.0, 70.0), (12.0, 30.0)])]


# ---- helpers the offline tools share

def test_the_array_yaw_decode_is_opendbcs_and_inverts():
  counts = np.linspace(-60, 60, 481)
  for scale, right in ((0.245, 0.49), (0.2511, -0.20), (0.246, 0.0)):
    deg = L.yaw_deg_s(counts, scale, right)
    assert deg == pytest.approx([yaw_rate_deg_s(c, scale, right) for c in counts])
    assert L.yaw_counts(-np.radians(deg), scale, right) == pytest.approx(counts, abs=1e-9)


def test_pressed_recently_covers_the_fade_after_a_press():
  pressed = np.zeros(100)
  pressed[10] = 1
  recent = L.pressed_recently(pressed, 30)
  assert not recent[:10].any() and recent[10:41].all() and not recent[41:].any()


def test_the_default_plant_is_the_fitted_knee():
  a, b = Plant(CAL, L.OL_J, 0.04), Plant(CAL, L.OL_J, 0.04, L.LOAD_KNEES[0])
  out = [(a.frame(e4, 25.0, 0.0), b.frame(e4, 25.0, 0.0)) for e4 in 800 * np.sin(np.arange(300) * 0.05)]
  assert all(x == y for x, y in out)


# ---- column load

def synthetic_load(truth, chunks=24, tq_scale=500.0, tq_offset=90.0, noise=40.0):
  ld = L.ColumnLoadLearner(CAL)
  rng = np.random.default_rng(1)
  for i in range(chunks):
    t = np.arange(N) * L.DT
    v = np.full(N, (4.0, 7.0, 12.0, 20.0)[i % 4])
    angle = (60.0 if i % 4 < 2 else 12.0) * np.sin(2 * np.pi * t / rng.uniform(4, 9)) + 3 * np.sin(2 * np.pi * t / 1.7)
    rate = np.gradient(angle, L.DT)
    tq = tq_offset + tq_scale * np.sin(2 * np.pi * t / rng.uniform(6, 15) + rng.uniform(0, 6))
    roll = np.full(N, rng.uniform(-0.03, 0.03))
    c = chunk(i * 100.0, v=v, angle=angle, rate=rate, tq=tq, roll=roll)
    X = L.load_regressors(angle, L.smooth(rate, 5), L.smooth(np.gradient(L.smooth(rate, 5), t), 5), v, roll, tq)
    assert ld.add_chunk(c, X @ truth + rng.normal(0, noise, N), i) == 'accepted'
  return ld


def test_the_load_fit_takes_the_drivers_torque_out():
  truth = np.array([-11.0, -0.12, -6.0, -360.0, -0.5, -75.0, -4.0, 0.55])
  ld = synthetic_load(truth)
  s = ld.best_shift()
  assert s == 0
  coef = ld.solve(s=s)
  assert coef == pytest.approx(truth, rel=0.03, abs=0.05)
  # the deployable bias is the one at the mean torque (the sensor's offset, a resting hand), as the recipe's is
  assert ld.tq_mean(s) == pytest.approx(90.0, abs=5.0)
  assert ld.model(coef, s).bias == pytest.approx(-75.0 + 0.55 * 90.0, abs=3.0)
  # every regime with data: the fit is on the firmware, the shipped A040 load (softer) under-asks turn-ins
  table = ld.regimes(s, 0)
  assert {'turn-in <8', 'turn-in 8-15', 'hold 8-15', 'unwind <8'} <= set(table)
  assert all(abs(fit) < 0.03 for _, _, fit in table.values())
  assert table['turn-in <8'][1] < -0.10


def test_a_frame_in_the_override_fade_or_past_the_torque_cap_is_left_out():
  ld = L.ColumnLoadLearner(CAL, fade_up_s=0.5)
  t = np.arange(N) * L.DT
  angle = 30 * np.sin(2 * np.pi * t / 6)
  pressed, tq = np.zeros(N), np.full(N, 100.0)
  pressed[1000:1100] = 1
  tq[3000:3200] = 1500.0
  c = chunk(angle=angle, rate=np.gradient(angle, L.DT), pressed=pressed, tq=tq)
  assert ld.add_chunk(c, np.zeros(N), 0) == 'accepted'
  fade = int((0.5 + L.LOAD_FADE_MARGIN_S) / L.DT)
  assert ld.n[0, 0].sum() == pytest.approx(N - (100 + fade) - 200 - 6 - (L.LOAD_SHIFTS + 2), abs=2)


def test_the_load_says_what_coverage_it_still_needs():
  ld = synthetic_load(np.array([-11.0, -0.12, -6.0, -360.0, -0.5, -75.0, -4.0, 0.55]), chunks=4)
  ok, progress, why = ld.check()
  assert not ok and progress < 1.0 and why.startswith('coverage: ') and 'min' in why and 'hands-off 20 s windows' in why


def short_drive(monkeypatch):
  """Ten minutes stand in for an owner's hours: the minimums and the identifiability yardstick shrink with them."""
  monkeypatch.setattr(L, 'LOAD_MIN_S', 8 * 60)
  monkeypatch.setattr(L, 'LOAD_PRIOR_S', 30.0)
  monkeypatch.setattr(L, 'OL_MIN_WINDOWS', 4)


def test_the_load_freezes_on_a_simulated_column_and_passes_the_open_loop_gate(driven, monkeypatch):
  short_drive(monkeypatch)
  ld = L.ColumnLoadLearner(dataclasses.replace(CAL, load=TRUE_LOAD))
  for i, c in enumerate(driven):
    ld.add_chunk(c, L.firmware_target(c['e4'], c['v'], c['rate'], c['ang'], ld.cal), i)
  assert ld.accepted >= len(driven) - 1
  ok, progress, why = ld.check()
  assert ok, why
  frozen = ld.freeze()
  assert frozen['friction_width_v'] == list(L.LOAD_KNEES[0])
  assert all(L.OL_GAIN[0] <= g <= L.OL_GAIN[1] for g in frozen['open_loop_gain'])
  for k, tol in (('k0', 0.15), ('k1', 0.15), ('friction', 0.15)):
    assert frozen[k] == pytest.approx(getattr(TRUE_LOAD, k), rel=tol)
  json.dumps(frozen)
  # a frozen load only watches: the same column leaves it alone, a column needing 1.3x the output marks it stale
  for i in range(L.LOAD_MONITOR_CHUNKS):
    c = driven[i % len(driven)]
    assert ld.add_chunk(c, L.firmware_target(c['e4'], c['v'], c['rate'], c['ang'], ld.cal), 100 + i) == 'monitored'
  assert not ld.stale()
  for i in range(L.LOAD_MONITOR_CHUNKS):
    c = driven[i % len(driven)]
    ld.add_chunk(c, 1.3 * L.firmware_target(c['e4'], c['v'], c['rate'], c['ang'], ld.cal), 200 + i)
  assert ld.stale()


def test_a_load_too_stiff_for_the_car_fails_the_open_loop_gate(driven, monkeypatch):
  short_drive(monkeypatch)
  ld = L.ColumnLoadLearner(CAL)
  for i, c in enumerate(driven):
    ld.add_chunk(c, L.firmware_target(c['e4'], c['v'], c['rate'], c['ang'], ld.cal), i)
  s = ld.best_shift()
  stiff = ld.solve(s=s) * np.array([2.5, 2.5, 1, 2.5, 1, 1, 1, 1])
  assert min(ld.open_loop(stiff, s, 0)) < L.OL_GAIN[0]


# ---- yaw decode

def yaw_drive(learner, index, t0, scale, right, zero_error, minutes=4, gps_hz=1.0):
  rng = np.random.default_rng(index)
  n = minutes * N
  t = t0 + np.arange(n) * L.DT
  counts = np.zeros(n)
  for start in range(1500, n - 2500, 3000):  # a 9 s turn every 30 s, alternating sides
    counts[start:start + 900] = rng.uniform(25, 50) * (1 if (start // 3000) % 2 else -1)
  counts = L.smooth(counts, 100)
  heading = np.cumsum(L.yaw_deg_s(counts, scale, right)) * L.DT
  tg = np.arange(t[0] + 1.0, t[-1], 1.0 / gps_hz)
  gps = np.c_[tg, (np.interp(tg - L.GPS_LAG, t, heading) + rng.normal(0, 0.3, len(tg))) % 360, np.full(len(tg), 12.0), np.ones(len(tg))]
  for i in range(minutes):
    w = slice(i * N, (i + 1) * N)
    g = gps[(gps[:, 0] >= t[w][0]) & (gps[:, 0] <= t[w][-1])]
    learner.add_chunk(chunk(yawc=counts[w] + zero_error, gps=g, t=t[w]), index * 100 + i)


@pytest.mark.parametrize("zero_error", [0.0, 0.3, -0.3])
def test_the_yaw_scale_survives_a_zero_error(zero_error):
  yaw = L.YawScaleLearner(0.245, 0.49)
  for d in range(7):
    yaw_drive(yaw, d, d * 1000.0, 0.2475, 0.12, zero_error)
  assert yaw.drives == 7
  ok, _, why = yaw.check()
  assert ok, why
  frozen = yaw.freeze()
  assert frozen['scale'] == pytest.approx(0.2475, rel=0.004)
  assert frozen['right'] == pytest.approx(0.12, abs=0.04)
  assert frozen['zero_error_counts'] == pytest.approx(-zero_error, abs=0.08)


def test_the_yaw_scale_waits_for_three_drives():
  yaw = L.YawScaleLearner(0.245, 0.49)
  for d in range(2):
    yaw_drive(yaw, d, d * 1000.0, 0.2475, 0.12, 0.0, minutes=10)
  ok, progress, why = yaw.check()
  assert not ok and '2/3 drives' in why and progress == pytest.approx(2 / 3)


def test_yaw_before_this_drives_zero_is_not_used():
  yaw = L.YawScaleLearner(0.245, 0.49)
  c = chunk(yawc=np.r_[np.full(N - 400, np.nan), np.zeros(400)])
  assert yaw.add_chunk(c, 0) == 'thin'
  c = chunk(100.0, yawc=np.r_[np.full(1000, np.nan), np.zeros(N - 1000)])
  assert yaw.add_chunk(c, 1) == 'no pairs'
  assert len(yaw.tail) == L.YAW_TAIL and yaw.tail[0, 0] > c['t'][1000]


# ---- rack map and the near-centre gain

def rack_chunks(decode, centre_gain=1.0, chunks=24):
  rack_map = HondaEpsRackMap(WHEELBASE, VGR, RACK)
  out = []
  for i in range(chunks):
    rng = np.random.default_rng(i)
    t = np.arange(N) * L.DT
    v = np.full(N, (3.5, 6.0, 8.0, 10.5, 13.5, 17.0)[i % 6])
    amplitude = (140.0, 60.0, 25.0, 10.0, 2.5, 8.0)[(i // 6 + i) % 6]
    angle = amplitude * np.sin(2 * np.pi * t / rng.uniform(12, 20)) + (8.0 if amplitude == 8.0 else 0.0) * np.sign(np.sin(2 * np.pi * t / 60))
    lagged = np.interp(t - np.interp(v, *L.WHEEL_TO_YAW_LAG), t, angle)
    k = np.array([-rack_map.curvature_from_angle(float(a), float(s), 0.0) for a, s in zip(lagged, v, strict=True)])
    k3 = -rack_map.curvature_from_angle(3.0, float(v[0]), 0.0)
    k = np.where(np.abs(lagged) < 3.0, centre_gain * k, k - np.sign(lagged) * (1.0 - centre_gain) * k3)  # a centre dead zone
    out.append(chunk(i * 100.0, v=v, angle=angle, rate=np.gradient(angle, L.DT), yawc=L.yaw_counts(k * v, *decode)))
  return out


def test_the_rack_fit_recovers_the_map_on_the_decode_it_is_given_and_waits_for_the_yaw():
  decode = (0.2475, 0.12)
  learner = L.HondaEpsCarLearner(CAL, WHEELBASE, VGR, YAW)
  assert learner.rack is not None and learner.yaw is not None
  for i, c in enumerate(rack_chunks(decode)):
    assert learner.rack.add_chunk(c, i) in ('accepted', 'thin')
  ok, _, why = learner.rack.check(decode)
  assert ok, why
  sf, bp, val = learner.rack.solve(decode)
  assert sf == pytest.approx(RACK.slip_factor, abs=1e-4)
  assert val == pytest.approx(np.interp(bp, RACK.ratio_bp, RACK.ratio_v), rel=0.01)
  # on the shipped decode (clockwise correction 0.49 against the car's 0.12) the same samples give another map
  assert learner.rack.solve((YAW[0], YAW[2]))[2][0] != pytest.approx(val[0], rel=0.005)
  learner.check()
  assert learner.rack.frozen is None and 'waiting for the yaw decode' in learner.reasons['rack'][1]
  learner.yaw.frozen = {'scale': decode[0], 'right': decode[1]}
  learner.check()
  assert learner.rack.frozen is None and learner.reasons['rack'][1].startswith('passed, confirming on the next check')
  learner.check()
  assert learner.rack.frozen is not None and learner.rack.frozen['yaw_decode'] == list(decode)
  assert learner.status()['rack'][0] == 'frozen'


def test_the_near_centre_gain_reads_a_dead_zone_and_the_reference_does_not():
  decode = (0.2475, 0.12)
  centre = L.NearCentreGain(HondaEpsRackMap(WHEELBASE, VGR, RACK))
  for c in rack_chunks(decode, centre_gain=0.6, chunks=36):
    centre.add_chunk(c)
  gains = centre.gains(decode)
  assert {'9-15', '15-30'} <= set(gains)
  for inside, _, reference, _ in gains.values():
    assert inside == pytest.approx(0.6, abs=0.05)
    assert reference is None or reference == pytest.approx(1.0, abs=0.05)


# ---- timing: measured only

def test_the_command_delay_part_only_measures():
  part = L.PlanTimingLearner()
  assert not hasattr(part, 'applied') and not hasattr(part, 'pending')

  def turning(i, late, delay):
    t = i * 100.0 + np.arange(N) * L.DT
    curvature = lambda x: 0.02 * np.sin(2 * np.pi * x / 8.0)  # noqa: E731
    v = np.full(N, 8.0)
    tm = t[::5]
    model = np.c_[tm + 0.02, tm, np.zeros(len(tm)), curvature(tm[:, None] + L.PLAN_T[None, :])]
    yaw = curvature(t - late - L.VSA_LATENCY) * v
    return chunk(t=t, v=v, model=model, cmd_delay=np.full(N, delay)), yaw

  for i in range(10):
    c, yaw = turning(i, 0.10, 0.12)
    assert part.add_chunk(c, yaw, i) == 'accepted'
  assert part.delay_s == 0.12 and part.restarts == 0
  ok, _, why = part.check()
  assert ok, why
  assert part.candidate()['shift_s']['all'] == pytest.approx(0.10, abs=0.011)
  # drives at another command delay start the measurement over: a shift belongs to the delay that ran
  c, yaw = turning(11, 0.0, 0.0)
  part.add_chunk(c, yaw, 11)
  assert part.delay_s == 0.0 and part.restarts == 1
  assert part.candidate()['shift_s']['all'] == pytest.approx(0.0, abs=0.011)


def test_the_model_delay_part_measures_town_bands():
  part = L.TimingLearner()
  for i in range(9):
    t = i * 100.0 + np.arange(N) * L.DT
    v = np.full(N, (4.0, 7.0, 12.0)[i % 3])
    act = 0.02 * np.sin(2 * np.pi * t / 7.0)
    yaw = 0.9 * np.interp(t - 0.20, t, act) * v
    part.add_chunk(chunk(t=t, v=v, act=act), yaw, i)
  ok, _, why = part.check()
  assert ok, why
  assert part.band_frozen == pytest.approx([0.20 - L.PIPELINE_OFFSET] * 3, abs=0.011)


# ---- torque sensor

def test_the_torque_sensor_model_finds_what_moving_the_wheel_puts_on_the_bar():
  model = L.TorqueSensorModel()
  rng = np.random.default_rng(0)
  for _ in range(3):
    t = np.arange(N) * L.DT
    angle = 20 * np.sin(2 * np.pi * t / 5) + 4 * np.sin(2 * np.pi * t / 1.3)
    rate = np.gradient(angle, L.DT)
    stop, s = np.zeros(N), 0.0
    for k in range(N):
      s = stop[k] = min(max(s + rate[k] * L.DT / FRICTION_WIDTH, -1.0), 1.0)
    tq = 90 - 0.25 * np.gradient(rate, L.DT) - 80 * stop - 150 * np.sin(np.radians(angle)) + rng.normal(0, 20, N)
    tq[2000:2040] += 1500   # a nudge between quiet flanks: the wheel's motion does not explain it, so it is left out
    tq[4000:4400] += 1500   # a long hold: its frames and the 3 s around them are left out
    model.add_chunk(chunk(angle=angle, rate=rate, tq=tq))
  out = model.result()
  assert out['offset'] == pytest.approx(90, abs=4) and out['inertia'] == pytest.approx(-0.25, abs=0.03)
  assert out['friction'] == pytest.approx(-80, abs=8) and out['imbalance'] == pytest.approx(-150, abs=20)
  assert 1.5 < out['minutes'] < 2.8 and out['r2'] > 0.9


# ---- the whole learner: result and saved state

def test_the_result_is_shadow_json_and_survives_a_save(driven):
  learner = L.HondaEpsCarLearner(CAL, WHEELBASE, VGR, YAW, identity='39990-TLA-A040|2e6a8802')
  for c in driven[:5]:
    learner.add_chunk(c)
  res = learner.result()
  assert json.loads(json.dumps(res)) == res
  assert res['shadow'] is True and res['calibration'] == 'crv_tla_a040' and set(res['parts']) == set(L.HondaEpsCarLearner.PARTS)
  assert res['parts']['load']['state'] == 'learning' and res['parts']['load']['candidate']['k0'] < 0
  blob = learner.to_bytes()
  assert len(blob) < 1_500_000
  again = L.HondaEpsCarLearner.from_bytes(blob, CAL, WHEELBASE, VGR, YAW, identity='39990-TLA-A040|2e6a8802')
  assert again is not None and again.result() == res
  again.add_chunk(driven[5])
  learner.add_chunk(driven[5])
  assert again.result() == learner.result()
  # another image, another calibration or garbage: start over
  assert L.HondaEpsCarLearner.from_bytes(blob, CAL, WHEELBASE, VGR, YAW, identity='39990-TLA-A040|other') is None
  assert L.HondaEpsCarLearner.from_bytes(blob, eps_cal.CRV_TLA_A220, WHEELBASE, VGR, YAW, identity='39990-TLA-A040|2e6a8802') is None
  assert L.HondaEpsCarLearner.from_bytes(b'not an npz', CAL, WHEELBASE, VGR, YAW) is None


def test_a_car_without_a_decoded_yaw_still_learns_its_load():
  learner = L.HondaEpsCarLearner(CAL, WHEELBASE, VGR, None)
  assert learner.yaw is None and learner.rack is None and learner.centre is None
  learner.add_chunk(chunk(yawc=np.full(N, np.nan)))
  status = learner.status()
  assert status['yaw'][0] == 'waiting' and status['rack'][0] == 'waiting' and status['load'][0] == 'learning'
  assert learner.result()['near_centre_gain'] is None


# ---- the daemon's plumbing

def car_state(v=10.0, angle=0.0, yaw_rate=0.0, standstill=False, pressed=False, fault=False):
  return SimpleNamespace(vEgo=v, aEgo=0.0, steeringAngleDeg=angle, steeringRateDeg=0.0, steeringTorque=50.0, steeringPressed=pressed,
                         leftBlinker=False, rightBlinker=False, standstill=standstill, steerFaultTemporary=fault, steerFaultPermanent=False,
                         yawRate=yaw_rate)


def test_chunks_are_a_minute_long_and_never_span_a_gap():
  builder = learnerd.FrameBuilder(YAW)
  builder.handle('sendcan', [SimpleNamespace(address=0xE4, dat=(-1200).to_bytes(2, 'big', signed=True) + bytes(3))], 0.0)
  builder.handle('carControl', SimpleNamespace(latActive=True), 0.0)
  builder.handle('vehicleParameters', SimpleNamespace(angleOffsetDeg=1.5, roll=0.01), 0.0)
  builder.handle('starpilotLateralState', SimpleNamespace(epsCommandDelay=0.12), 0.0)
  out = [builder.handle('carState', car_state(), i * 0.01) for i in range(learnerd.CHUNK_FRAMES + 1)]
  assert all(c is None for c in out[:-1])
  c = out[-1]
  assert len(c['t']) == learnerd.CHUNK_FRAMES and set(L.CHUNK_FIELDS) <= set(c)
  assert c['e4'][0] == -1200 and c['lat'][0] == 1 and c['off'][0] == 1.5 and c['cmd_delay'][0] == pytest.approx(0.12) and c['eps_ok'].all()
  # a gap ends the chunk; a stub shorter than MIN_CHUNK_FRAMES is dropped
  t0 = 100.0
  assert builder.handle('carState', car_state(), t0) is None
  for i in range(learnerd.MIN_CHUNK_FRAMES + 50):
    assert builder.handle('carState', car_state(), t0 + 0.01 * (i + 1)) is None
  c = builder.handle('carState', car_state(), t0 + 60.0)
  assert c is not None and len(c['t']) == learnerd.MIN_CHUNK_FRAMES + 51
  assert builder.flush() is None


def test_the_yaw_counts_come_back_out_of_carstate_once_the_zero_is_learned():
  builder = learnerd.FrameBuilder(YAW)
  yaw_rate = -np.radians(yaw_rate_deg_s(20.0, YAW[0], YAW[2]))  # carState.yawRate is left-positive
  stop = SETTLE_FRAMES + LEARN_FRAMES
  for i in range(100):
    builder.handle('carState', car_state(yaw_rate=yaw_rate), i * 0.01)
  for i in range(100, 100 + stop):
    builder.handle('carState', car_state(v=0.0, standstill=True), i * 0.01)
  for i in range(100 + stop, learnerd.MIN_CHUNK_FRAMES + 100):
    builder.handle('carState', car_state(yaw_rate=yaw_rate), i * 0.01)
  c = builder.flush()
  assert np.isnan(c['yawc'][:100 + stop - 1]).all()
  assert c['yawc'][100 + stop:] == pytest.approx(20.0, abs=1e-4)
  # a replay decodes the logged 0x94 with carstate's own zero learning
  raw = learnerd.FrameBuilder(YAW, raw_yaw=True)
  for i in range(learnerd.MIN_CHUNK_FRAMES + 100):
    stopped = i < stop + 10
    count = 511 if stopped else 531
    raw.handle('can', [SimpleNamespace(address=0x94, src=1, dat=bytes([count >> 2, (count & 3) << 6]))] * 60, i * 0.01)
    raw.handle('carState', car_state(v=0.0 if stopped else 10.0, standstill=stopped), i * 0.01)
  assert raw.flush()['yawc'][-1] == pytest.approx(20.0, abs=1e-6)


class FakeParams:
  def __init__(self, **values):
    self.values = dict(values)

  def get(self, key):
    return self.values.get(key)

  def put(self, key, value):
    self.values[key] = value

  def put_bool(self, key, value):
    self.values[key] = "1" if value else "0"


def test_the_learner_is_on_unless_turned_off():
  assert learnerd.should_run(FakeParams(HondaEpsLearner="0"), None) is False
  ptm = _params(b'39990-TLA,A040\x00\x00', CAR.HONDA_CRV_5G)
  assert learnerd.should_run(FakeParams(), ptm) is True


def test_the_learner_runs_only_where_the_honda_eps_controller_steers():
  on = FakeParams(HondaEpsLearner="1")
  ptm = _params(b'39990-TLA,A040\x00\x00', CAR.HONDA_CRV_5G)
  assert learnerd.should_run(on, ptm) is True
  assert learnerd.should_run(on, _params(b'39990-TLA-A040\x00\x00', CAR.HONDA_CRV_5G)) is False  # a stock EPS
  wheelbase, vgr, yaw, identity = learnerd.learner_setup(ptm, CAL)
  assert identity == '39990-TLA-A040|2e6a8802'  # the EPS version and the corrected PTM image the law was built for
  assert wheelbase == pytest.approx(ptm.wheelbase) and vgr is VGR and yaw == YAW
  # the Ridgeline has no decoded 0x94: its learner gets no yaw calibration
  ridgeline = _params(b'39990-T6Z,A110\x00\x00', CAR.HONDA_RIDGELINE)
  assert learnerd.learner_setup(ridgeline, eps_cal.RIDGELINE_T6Z_A110)[2] is None


def test_the_runner_publishes_saves_resumes_and_resets(driven, tmp_path):
  setup = (WHEELBASE, VGR, YAW, '39990-TLA-A040|2e6a8802')
  params = FakeParams()
  runner = learnerd.LearnerRunner(params, CAL, setup, str(tmp_path))
  assert params.values['HondaEpsLearnerResult']['chunks'] == 0
  for c in driven[:learnerd.SAVE_EVERY]:
    runner.add(c)
  assert (tmp_path / learnerd.STATE_FILE).exists()
  published = params.values['HondaEpsLearnerResult']
  assert published['chunks'] == learnerd.SAVE_EVERY and published['shadow'] is True
  json.dumps(published)
  assert learnerd.LearnerRunner(params, CAL, setup, str(tmp_path)).learner.chunks == learnerd.SAVE_EVERY
  # another PTM image under the same version string: the saved state is not this car's any more
  other = learnerd.LearnerRunner(params, CAL, setup[:3] + ('39990-TLA-A040|reflashed',), str(tmp_path))
  assert other.learner.chunks == 0
  params.put_bool("HondaEpsLearnerReset", True)
  fresh = learnerd.LearnerRunner(params, CAL, setup, str(tmp_path))
  assert fresh.learner.chunks == 0 and params.values["HondaEpsLearnerReset"] == "0" and not (tmp_path / learnerd.STATE_FILE).exists()
  assert params.values['HondaEpsLearnerResult']['chunks'] == 0
