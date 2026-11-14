from types import SimpleNamespace

from openpilot.starpilot.longitudinal import bosch_a_turnoff as T
from openpilot.starpilot.longitudinal.bosch_a_smooth import BRAKE_RELEASE_JERK, BoschASmooth

DT = 0.05


def lead(tid=22, d=20.0, v=-5.0, y=-0.8, present=True):
  return SimpleNamespace(present=present, radarTrackId=tid, dRel=d, vRel=v, yRel=y)


GONE = lead(present=False, tid=-1, d=0.0, v=0.0, y=0.0)


def run_release(fl, raw_seq, prev_target=-3.0):
  """One braking cycle with the lead, then the lead is gone; raw_seq gives the raw tracks per cycle after that."""
  assert fl.update(lead(), prev_target, {22: -0.8}) is None
  return [fl.update(GONE, prev_target, raw) for raw in raw_seq]


def test_confirmed_exit_lets_off_fast_and_withholds_gas():
  fl = T.FastLetoff(DT)
  out = run_release(fl, [{22: -1.0}, {22: -1.6}, {22: -2.0}, {}])  # gone at 2.0 m: past CLEAR_Y, keeps going
  assert out[0] is None and out[1] == T.FAST_JERK
  assert fl.fired == 1 and fl.no_gas


def test_track_vanishing_without_moving_out_keeps_base_letoff():
  # 84 s7 / a2 s42 shape: the track disappears near 1.25 m with little lateral growth
  fl = T.FastLetoff(DT)
  out = run_release(fl, [{22: -0.85}, {}, {}, {}])
  assert all(o is None for o in out)
  assert fl.fired == 0 and fl.aborted == 1 and not fl.no_gas


def test_track_staying_in_lane_times_out():
  fl = T.FastLetoff(DT)
  n = int(T.CONFIRM_S / DT) + 4
  out = run_release(fl, [{22: -0.9}] * n)
  assert all(o is None for o in out) and fl.aborted == 1


def test_no_raw_tracks_never_fires():
  fl = T.FastLetoff(DT)
  out = run_release(fl, [{}] * 20)
  assert all(o is None for o in out) and fl.fired == 0


def test_closing_lead_cancels_fast():
  fl = T.FastLetoff(DT)
  run_release(fl, [{22: -1.0, 30: 0.0}, {22: -1.6, 30: 0.0}])
  assert fl.fast_s > 0.0
  assert fl.update(lead(tid=30, d=25.0, v=-3.0, y=0.0), -2.0, {22: -2.0, 30: 0.0}) is None
  assert not fl.no_gas


def test_watched_track_vanishing_close_cancels():
  fl = T.FastLetoff(DT)
  run_release(fl, [{22: -1.0}, {22: -1.6}])
  assert fl.fast_s > 0.0
  assert fl.update(GONE, -2.0, {}) is None and not fl.no_gas


def test_no_trigger_without_a_real_brake():
  fl = T.FastLetoff(DT)
  out = run_release(fl, [{22: -2.0}] * 5, prev_target=-0.2)
  assert all(o is None for o in out) and fl.pend is None


def test_raw_track_y():
  pts = [SimpleNamespace(trackId=22, yRel=-1.5), SimpleNamespace(trackId=3, yRel=0.4)]
  class SM:
    valid = {'radarTracks': True}
    alive = {'radarTracks': True}
    def __getitem__(self, k):
      return SimpleNamespace(points=pts)
  sm = SM()
  assert T.raw_track_y(sm) == {22: -1.5, 3: 0.4}
  sm.valid['radarTracks'] = False
  assert T.raw_track_y(sm) == {}
  assert T.raw_track_y({}) == {}


def _smooth(monkeypatch, radar=True):
  import openpilot.starpilot.longitudinal.bosch_a_smooth as bs
  monkeypatch.setattr(bs, 'vehicle_supported', lambda CP: True)
  monkeypatch.setattr(bs, 'GHOST_ARM', False)  # these pin the FastLetoff path; the ghost let-off has its own tests
  return BoschASmooth(SimpleNamespace(radarUnavailable=not radar), DT)


def test_smooth_step_fast_letoff_and_no_gas(monkeypatch):
  sm = _smooth(monkeypatch)
  assert sm.enabled and sm.radar
  prev = sm.step(-3.0, -3.0, False, lead_one=lead(), raw_y={22: -0.8})
  prev = sm.step(prev, 0.8, False, lead_one=GONE, raw_y={22: -1.0})
  base_rise = BRAKE_RELEASE_JERK * DT
  assert prev <= -3.0 + 1e-6  # dwell / pending: no fast rise yet
  nxt = sm.step(prev, 0.8, False, lead_one=GONE, raw_y={22: -1.6})
  assert abs((nxt - prev) - T.FAST_JERK * DT) < 1e-6 and (nxt - prev) > base_rise
  for _ in range(20):
    nxt = sm.step(nxt, 0.8, False, lead_one=GONE, raw_y={22: -2.5})
    assert nxt <= 0.0  # no gas while the no-gas window runs
  assert sm.fast_letoff.fired == 1


def test_smooth_step_without_radar_never_fast(monkeypatch):
  sm = _smooth(monkeypatch, radar=False)
  assert sm.enabled and not sm.radar
  prev = sm.step(-3.0, -3.0, False, lead_one=lead(), raw_y={22: -0.8})
  for raw in ({22: -1.0}, {22: -1.6}, {22: -2.5}):
    nxt = sm.step(prev, 0.8, False, lead_one=GONE, raw_y=raw)
    assert nxt - prev <= BRAKE_RELEASE_JERK * DT + 1e-6
    prev = nxt
  assert sm.fast_letoff.fired == 0


def test_smooth_step_without_lead_keeps_base(monkeypatch):
  # upstream planner mirror calls step(prev, target, reset) only
  sm = _smooth(monkeypatch)
  prev = sm.step(-3.0, -3.0, False)
  for _ in range(6):
    nxt = sm.step(prev, 0.8, False)
    assert nxt - prev <= BRAKE_RELEASE_JERK * DT + 1e-6
    prev = nxt


def glead(tid=22, d=20.0, v=-5.0, y=-0.8, v_lead=8.0, a_lead=-1.0, present=True):
  return SimpleNamespace(present=present, radarTrackId=tid, dRel=d, vRel=v, yRel=y, vLeadK=v_lead, aLeadK=a_lead)


GGONE = glead(present=False, tid=-1, d=0.0, v=0.0, y=0.0, v_lead=0.0, a_lead=0.0)


def _ghost_smooth(monkeypatch, radar=True):
  import openpilot.starpilot.longitudinal.bosch_a_smooth as bs
  monkeypatch.setattr(bs, 'vehicle_supported', lambda CP: True)
  monkeypatch.setattr(bs, 'GHOST_ARM', True)
  return BoschASmooth(SimpleNamespace(radarUnavailable=not radar), DT)


def test_smooth_ghost_turner_lets_off_fast_without_gas(monkeypatch):
  # cc shape through the bridge smoother: braking lead released, raw track then moves out past 1.5 m
  sm = _ghost_smooth(monkeypatch)
  prev = sm.step(-3.0, -3.0, False, lead_one=glead(), raw_y={22: -0.8}, v_ego=13.0, model_lead0=(0.9, 21.5))
  prev = sm.step(prev, 0.8, False, lead_one=GGONE, raw_y={22: -0.9}, v_ego=13.0, model_lead0=(0.9, 21.5))
  assert prev <= -3.0 + 1e-6  # no clear yet: dwell holds the first rise tick
  out = sm.step(prev, 0.8, False, lead_one=GGONE, raw_y={22: -1.6}, v_ego=13.0, model_lead0=(0.9, 21.5))
  assert out - prev > BRAKE_RELEASE_JERK * DT + 1e-6 and out <= 0.0  # cleared: faster than base, still no gas
  assert sm.ghost.no_gas


def test_smooth_ghost_dropout_keeps_base(monkeypatch):
  # 84 s7 shape: raw track vanishes near the lane, camera still sees it: base let-off only, no gas
  sm = _ghost_smooth(monkeypatch)
  prev = sm.step(-3.0, -3.0, False, lead_one=glead(d=12.5, v=-8.0, v_lead=6.0), raw_y={22: -1.19}, v_ego=14.0,
                 model_lead0=(0.9, 14.0))
  for _ in range(10):
    nxt = sm.step(prev, 0.5, False, lead_one=GGONE, raw_y={}, v_ego=14.0, model_lead0=(0.9, 14.0))
    assert nxt <= max(prev + BRAKE_RELEASE_JERK * DT, -1e9) and nxt <= 0.0
    prev = nxt


def test_smooth_ghost_runs_without_radar(monkeypatch):
  # camera-only lead (tid -1), camera clears for 0.3 s: fast let-off with radar off
  sm = _ghost_smooth(monkeypatch, radar=False)
  prev = sm.step(-3.0, -3.0, False, lead_one=glead(tid=-1), raw_y={}, v_ego=13.0, model_lead0=(0.9, 21.5))
  outs = []
  for _ in range(8):
    prev = sm.step(prev, 0.5, False, lead_one=GGONE, raw_y={}, v_ego=13.0, model_lead0=(0.1, 80.0))
    outs.append(prev)
  assert outs[-1] - outs[-2] > BRAKE_RELEASE_JERK * DT + 1e-6
