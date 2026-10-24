"""Saved Ford release intent is consumed before construction, with exact admission."""
from types import SimpleNamespace
import pytest
from opendbc.car import gen_empty_fingerprint
from opendbc.car.ford.interface import CarInterface
from opendbc.car.ford.values import CAR
from openpilot.starpilot.car.ford.longitudinal_preferences import prepare_release_long
from openpilot.starpilot.tests.ford_lifecycle_helpers import FORD_FACTORIES


def saved(tmp_path, alpha=b'1', safe=b'0'):
  for key, value in [('AlphaLongitudinalEnabled', alpha), ('SafeMode', safe)]:
    if value is not None:
      (tmp_path / key).write_bytes(value)
  return SimpleNamespace(get_param_path=lambda key: str(tmp_path / key))


@pytest.mark.parametrize('identity,base', FORD_FACTORIES)
@pytest.mark.parametrize('manual', [False, True])
@pytest.mark.parametrize('offset', [0, 4])
def test_release_long_changes_only_selected_owner_and_long_selection(identity, base, manual, offset, tmp_path):
  fp = gen_empty_fingerprint()
  if not manual:
    fp[offset][0x5A] = 8
  fp[offset + 2].update({0x3D6: 8, 0x186: 8})
  stock = CarInterface.get_params(identity, fp, [], False, True, False)
  stock.carVin = '0' * 17
  stock.fuzzyFingerprint = True
  before = stock.to_dict()
  selected = prepare_release_long(stock, saved(tmp_path), is_release=True, enabled=True)
  expected = stock.as_reader().as_builder()
  expected.openpilotLongitudinalControl = True
  expected.safetyConfigs[-1].safetyParam = base | 1
  assert stock.to_dict() == before
  assert selected.to_dict() == expected.to_dict()


@pytest.mark.parametrize('alpha,safe,release,enabled', [
  (None, b'0', True, True), (b'0', b'0', True, True), (b'1junk', b'0', True, True),
  (b'1', b'1', True, True), (b'1', b'bad', True, True), (b'1', b'0', False, True),
  (b'1', b'0', True, False),
])
def test_release_opt_in_off_invalid_safe_mode_debug_and_disabled_stay_unchanged(alpha, safe, release, enabled, tmp_path):
  fp = gen_empty_fingerprint()
  fp[0][0x5A] = 8
  cp = CarInterface.get_params(CAR.FORD_MUSTANG_MACH_E_MK1, fp, [], False, True, False)
  assert prepare_release_long(cp, saved(tmp_path, alpha, safe), is_release=release, enabled=enabled) is cp


@pytest.mark.parametrize('restriction', ['secoc', 'extra-panda', 'angle', 'foreign-brand'])
def test_release_never_promotes_unowned_configuration(restriction, tmp_path):
  fp = gen_empty_fingerprint()
  fp[0][0x5A] = 8
  fp[2].update({0x3D6: 16 if restriction == 'secoc' else 8, 0x186: 16 if restriction == 'secoc' else 8})
  cp = CarInterface.get_params(CAR.FORD_MUSTANG_MACH_E_MK1, fp, [], False, True, False)
  if restriction == 'extra-panda':
    cp.safetyConfigs = [cp.safetyConfigs[0], cp.safetyConfigs[0]]
  elif restriction == 'angle':
    cp.safetyConfigs[-1].safetyParam = 130
  elif restriction == 'foreign-brand':
    cp.brand = 'hyundai'
  assert prepare_release_long(cp, saved(tmp_path), is_release=True, enabled=True) is cp
