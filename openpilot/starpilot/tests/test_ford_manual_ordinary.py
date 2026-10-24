"""Manual AOL marking cannot replace existing ordinary/angle configuration words."""
from pathlib import Path
from unittest.mock import patch
import pytest
from opendbc.car import car_helpers, gen_empty_fingerprint, structs
from opendbc.car.ford.values import CAR
from openpilot.cereal import messaging
from openpilot.common.params import Params
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.car import card as card_module


@pytest.mark.parametrize('identity,fd', [(CAR.FORD_ESCAPE_MK4, False), (CAR.FORD_MUSTANG_MACH_E_MK1, True)])
@pytest.mark.parametrize('alpha', [False, True])
@pytest.mark.parametrize('release', [False, True])
@pytest.mark.parametrize('offset', [0, 4])
def test_actual_manual_angle_startup_preserves_original_unmarked_owner(identity, fd, alpha, release, offset, monkeypatch):
  monkeypatch.setenv('SIMULATION', '1')
  monkeypatch.setenv('REPLAY', '1')
  monkeypatch.setenv('AOL_REPLAY_RUNTIME', '0')
  fp = gen_empty_fingerprint()
  fp[offset + 2].update({0x3D6: 8, 0x186: 8})
  observed = (identity, fp, '0' * 17, [], structs.CarParams.FingerprintSource.can, True)
  with OpenpilotPrefix():
    saved = Params()
    for key, value in [('OpenpilotEnabledToggle', True), ('AlwaysOnLateral', False), ('SafeMode', False),
                       ('AlphaLongitudinalEnabled', alpha), ('IsReleaseBranch', release), ('FordHumanTurnDetection', False)]:
      saved.put_bool(key, value, block=True)
    Path(saved.get_param_path('FordLateralMode')).write_bytes(b'1')
    with patch.object(car_helpers, 'fingerprint', return_value=observed), \
         patch.object(card_module, 'can_comm_callbacks', return_value=(lambda *args: [], lambda frames: None)), \
         patch.object(card_module.messaging, 'recv_one_retry', return_value=messaging.new_message('can', 1)):
      host = card_module.Car()
    try:
      assert host.CP.transmissionType == structs.CarParams.TransmissionType.manual
      assert host.CP.alternativeExperience == 0 and host.aol_card_intent is None
      assert host.CP.minEnableSpeed == pytest.approx(20 * .44704)
      assert host.CP.safetyConfigs[-1].safetyParam == 128 + (2 if fd else 0) + int(alpha and not release)
      assert host.CP.openpilotLongitudinalControl == bool(alpha and not release)
      assert host.CI.CC.bp_lat is not None
      if offset:
        assert host.CP.safetyConfigs[0].safetyModel == structs.CarParams.SafetyModel.noOutput
        assert host.CP.safetyConfigs[0].safetyParam == 0
      assert saved.get_bool('AlphaLongitudinalEnabled') == alpha
    finally:
      host.vehicle_startup.close()
