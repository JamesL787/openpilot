import json
import math

import numpy as np
import pytest

from openpilot.tools.longitudinal import bosch_hill_sim as sim


@pytest.fixture(autouse=True)
def plant_hill_default():
  sim.HILL_K[:] = [1.0, 1.0]
  yield
  sim.HILL_K[:] = [1.0, 1.0]


def test_plant_steady_state_gas_holds_speed():
  # the warm-start gas for a flat-road speed must cancel road load, or every scenario starts with a launch
  for mph in (30, 45, 65):
    v = mph * sim.MPH
    need = -(sim.R0 + sim.R2 * v * v)
    u = (need - sim.STEP) / sim.S1 if need - sim.STEP <= sim.S1 * sim.UK else sim.UK + (need - sim.STEP - sim.S1 * sim.UK) / sim.S2
    assert sim.drive(u) + sim.R0 + sim.R2 * v * v == pytest.approx(0.0, abs=1e-9)


def test_flat_road_holds_set_speed():
  sc = sim.Scenario('flat_45', 60.0, 45 * sim.MPH)
  m, rec = sim.run(sc, 'head')
  assert abs(m['peak_over_mph']) < 1.0
  assert math.isnan(m['climb_under_mph'])
  assert abs(rec['v'][-1] - 45 * sim.MPH) < 0.5
  assert m['t_gas_sat_s'] == 0.0
  assert math.isnan(m['v_vs_log_rms_mph'])


def test_same_seed_same_answer():
  sc = sim.Scenario('up4', 60.0, 45 * sim.MPH, grade=sim.hill_profile(4, 20 * 45 * sim.MPH))
  a, ra = sim.run(sc, 'learner_min', seed=3)
  b, rb = sim.run(sc, 'learner_min', seed=3)
  assert ra == rb
  assert a.keys() == b.keys()
  for k in a:
    assert a[k] == b[k] or (math.isnan(a[k]) and math.isnan(b[k])), k


def test_climb_slows_car_and_is_scored():
  v = 45 * sim.MPH
  m, _ = sim.run(sim.Scenario('up6', 20 + 1300 / v + 25, v, grade=sim.hill_profile(6, 20 * v)), 'head')
  assert m['climb_under_mph'] < 0.0


def test_scenario_a_needs_a_route(capsys):
  names = [sc.name for sc in sim.scenarios('ae')]
  assert names == ['e_flat_30', 'e_flat_45', 'e_flat_65']
  assert 'scenario a skipped' in capsys.readouterr().err


def _route(n=400, v0=15.0, a=0.2):
  t = 100.0 + np.arange(n) * sim.RDT
  v = v0 + a * (t - t[0])
  z = np.zeros(n)
  return {'t': t, 'v': v, 'aE': z + a, 'gp': z, 'bp': z, 'vcruise': z + 20.0, 'la': z + 1, 'acmd': z + a, 'ccp': z,
          'alt': z, 'aT': z + a, 'gas': z}


def test_replayed_command_starts_at_logged_speed(tmp_path):
  R = _route()
  frames = [{'t': float(t), 'v_ego': float(v), 'engaged': True, 'out': {'b0.075': 0.2}} for t, v in zip(R['t'], R['v'], strict=True)]
  f = tmp_path / 'frames.json'
  f.write_text(json.dumps({'meta': {}, 'frames': frames}))
  route = {'R': R, 'window': (100.0, 119.0), 'name': 'x', 'vset': None, 'frames': (f, 'b0.075')}
  (sc,) = sim.scenarios('a', route=route)
  assert sc.name == 'a_x_100-119_pitch_b0.075'
  assert sc.vset(0.0) == pytest.approx(20.0)  # logged set speed
  m, rec = sim.run(sc, 'head')
  assert rec['v'][0] == pytest.approx(15.0, abs=0.05)
  assert m['v_vs_log_rms_mph'] < 2.0


def test_frames_variant_missing_names_the_ones_there(tmp_path):
  R = _route()
  frames = [{'t': float(t), 'v_ego': float(v), 'engaged': True, 'out': {'mvl': 0.0}} for t, v in zip(R['t'], R['v'], strict=True)]
  f = tmp_path / 'frames.json'
  f.write_text(json.dumps({'meta': {}, 'frames': frames}))
  with pytest.raises(SystemExit, match='mvl'):
    sim.frames_atarget(f, 'b0.075', R, (100.0, 119.0))
