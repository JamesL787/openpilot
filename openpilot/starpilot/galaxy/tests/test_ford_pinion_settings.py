"""Actual typed Params, Galaxy parked write, and startup configuration for pinion."""
from pathlib import Path
import tempfile

import pytest
from opendbc.car import gen_empty_fingerprint
from opendbc.car.ford.pinion import KEY, GEOMETRY, configured
from opendbc.car.ford.values import CAR
from opendbc.car.ford.tests.test_three_ports import params as ford_params
from openpilot.common.params import Params
from openpilot.starpilot.galaxy.settings import AuthorityContext, SettingsGateway


def test_real_galaxy_typed_parked_selection_and_stale_dependency():
  with tempfile.TemporaryDirectory() as directory:
    params = Params(directory)
    assert params.get_default_value(KEY) is False
    params.put_bool('SafeMode', False, block=True)
    params.put_bool('AlwaysOnLateral', False, block=True)
    cp = ford_params(CAR.FORD_EXPLORER_MK6)
    parked = True
    class TestContext:
      def sample(self) -> AuthorityContext:
        return AuthorityContext(parked, cp, cp.as_reader().as_builder().to_bytes())

    gateway = SettingsGateway(params, TestContext())
    try:
      page = gateway.page('torque', 'pinion-test', b'generation')
      index, row = next((i, row) for i, row in enumerate(page['rows']) if row['label'] == 'Use Pinion Yaw Sensor')
      assert row['choices'] == ['Off', 'On'] and row['available']
      intent = gateway.preview(page['view'], index, 0, 'pinion-test', b'generation', value='On')
      assert gateway.confirm(intent['intent'], 'pinion-test', b'generation')
      assert params.get(KEY) is True
      assert Path(params.get_param_path(KEY)).read_bytes() == b'1'
      assert not configured(cp)  # Saved preference cannot mutate the current driving configuration.
      parked = False
      page = gateway.page('torque', 'pinion-test', b'generation')
      row = next(row for row in page['rows'] if row['label'] == 'Use Pinion Yaw Sensor')
      assert not row['available']
    finally:
      gateway.close()


@pytest.mark.parametrize('identity', list(GEOMETRY))
def test_actual_factory_applies_before_controller_and_published_cp(identity):
  from openpilot.starpilot.tests.test_vehicle_preferences import TestVehicleStartupPreferences
  helper = TestVehicleStartupPreferences()
  helper.setUp()
  try:
    helper.raw('SafeMode', b'0')
    helper.raw('AlwaysOnLateral', b'0')
    helper.params.put_bool('AlphaLongitudinalEnabled', False, block=True)
    helper.params.put_bool('IsReleaseBranch', False, block=True)
    fp = gen_empty_fingerprint()
    fp[0][0x5A] = 8
    fp[2].update({0x3D6: 8, 0x186: 8})
    host, constructed, published = helper.start(identity, key=KEY, requested=True, observed=fp,
                                                capture=lambda ci: configured(ci.CP))
    assert constructed == [True]
    assert configured(published)
    assert host.CI.CP.to_dict() == published.to_dict()
  finally:
    helper.doCleanups()
