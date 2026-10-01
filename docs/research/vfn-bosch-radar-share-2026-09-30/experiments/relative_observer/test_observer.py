import ast
from pathlib import Path

import numpy as np
import pytest

from opendbc.car.can_definitions import CanData
from opendbc.car.honda.hondacan import CanBus
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR

from replay import HERE, REPO, load


ri_module = load('observer_under_test', HERE / 'radar_interface.py')
baseline = load('observer_test_baseline', HERE / 'radar_interface_baseline.py')


@pytest.fixture
def rig():
  cp = CarInterface.get_non_essential_params(CAR.HONDA_CIVIC_BOSCH)
  cp.radarUnavailable = False
  # Reuse only the existing raw frame builders, without executing the test
  # module's global Params writes or importing its fixtures.
  source = ast.parse((REPO / 'opendbc_repo/opendbc/car/honda/tests/test_bosch_a_radar.py').read_text())
  names = {'make_f0', 'make_f1', 'make_f2', 'make_f3', 'make_aux', 'make_main_frames', 'sweep'}
  tree = ast.Module(body=[n for n in source.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
  scope = dict(vars(ri_module), CanData=CanData, BUS=CanBus(cp).camera)
  exec(compile(tree, '<existing wire frame builders>', 'exec'), scope)
  return cp, scope['sweep']


@pytest.mark.parametrize('tau', [0.3, 0.6, 0.9])
def test_constant_motion_at_irregular_cadence(tau):
  o = ri_module._BoschARelativeMotion(tau=tau)
  t = 0.0
  for i in range(80):
    value = o.update(t, 60.0 - 2.0 * t, -2.0)
    assert value == pytest.approx(-2.0, abs=1e-10)
    assert np.linalg.eigvalsh(o.p).min() >= -1e-12
    t += 0.05 if i % 2 else 0.09


def test_exact_constant_acceleration_basis():
  o = ri_module._BoschARelativeMotion()
  o.update(0.0, 60.0, -2.0)
  o.x[2] = -1.0
  for i in range(1, 20):
    t = 0.07 * i
    u = -2.0 - (t - o.tau * (1.0 - np.exp(-t / o.tau)))
    v = o.update(t, 60.0 - 2.0 * t - 0.5 * t * t, u)
    assert v == pytest.approx(-2.0 - t, abs=1e-9)


def test_outlier_does_not_rebase_observer():
  o = ri_module._BoschARelativeMotion()
  for i in range(20):
    o.update(i * 0.07, 60.0 - i * 0.14, -2.0)
  prior = o.x.copy()
  assert o.update(1.4, 60.0 - 2.8 + 5.9, -2.0) is None
  np.testing.assert_array_equal(o.x, prior)
  assert o.rejected == 1
  assert o.update(1.47, 60.0 - 2.94, -2.0) == pytest.approx(-2.0)


@pytest.mark.parametrize('t', [0.0, -0.1, float('nan')])
def test_duplicate_backward_nonfinite_observations(t):
  o = ri_module._BoschARelativeMotion()
  o.update(0.0, 20.0, -2.0)
  assert o.update(t, 5.0, -9.0) is None
  assert o.accepted == 1
  assert o.x[0] == 20.0


def test_stale_history_reinitializes():
  o = ri_module._BoschARelativeMotion()
  o.update(0.0, 20.0, -2.0)
  assert o.update(0.3, 90.0, 3.0) == 3.0
  assert o.accepted == 1
  assert o.x[2] == 0.0


@pytest.mark.parametrize('raw', [0, 1728])
def test_native_rail_preserved_as_measured(rig, raw):
  cp, sweep = rig
  ri = ri_module.RadarInterface(cp)
  ri.bosch_a_velocity_observer_params = {}
  for i in range(4):
    rr = ri.update(sweep(0, i, 7, 1000, 1024, 1 + i * 2, i * 70_000_000,
                         with_aux=True, direct_vrel_raw=raw, direct_vrel_uncertainty_raw=80))
  assert len(rr.points) == 1
  assert rr.points[0].measured
  assert rr.points[0].vRel == (raw - 864) / 64.0
  assert ri._tracks[1].velocity_observer is None


def test_migration_preserves_observer_lifecycle_replacement_clears_it(rig):
  cp, sweep = rig
  ri = ri_module.RadarInterface(cp)
  ri.bosch_a_velocity_observer_params = {}
  ri.update(sweep(0, 0, 7, 1000, 1024, 1, 0, with_aux=True,
                  direct_vrel_raw=864, direct_vrel_uncertainty_raw=80))
  observer = ri._tracks[1].velocity_observer
  rr = ri.update(sweep(1, 1, 7, 1000, 1024, 3, 70_000_000, with_aux=True,
                       direct_vrel_raw=864, direct_vrel_uncertainty_raw=80))
  assert len(rr.points) == 1
  assert ri._tracks[1].velocity_observer is observer
  assert observer.accepted == 2
  ri.update(sweep(1, 2, 7, 1000, 1024, 55, 140_000_000, with_aux=True,
                  direct_vrel_raw=864, direct_vrel_uncertainty_raw=80))
  assert ri._tracks[1].velocity_observer is not observer
  assert ri._tracks[1].velocity_observer.accepted == 1


def test_disabled_matches_baseline_on_wire(rig):
  cp, sweep = rig
  a, b = baseline.RadarInterface(cp), ri_module.RadarInterface(cp)
  for i in range(12):
    packet = sweep(0, i, 7, 1000 - 2 * i, 1024, 1 + i * 2, i * 70_000_000,
                   with_aux=True, direct_vrel_raw=800, direct_vrel_uncertainty_raw=80)
    pa, pb = a.update(packet), b.update(packet)
    assert [(p.trackId, p.dRel, p.yRel, p.vRel, p.measured) for p in pa.points] == [
      (p.trackId, p.dRel, p.yRel, p.vRel, p.measured) for p in pb.points]


def test_nidec_implementation_identical():
  def method(path):
    tree = ast.parse(Path(path).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RadarInterface')
    return next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_update_nidec')
  assert ast.dump(method(HERE / 'radar_interface.py')) == ast.dump(method(HERE / 'radar_interface_baseline.py'))
