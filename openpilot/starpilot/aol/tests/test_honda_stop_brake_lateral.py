"""Holding the brake at a stop keeps Honda AOL lateral when the pause-on-brake setting is off.

A stopped Clarity's vEgo reads slightly negative (-0.003 m/s) while standstill flickers, and the lateral inhibit read
that as "below the pause speed 0", withdrawing lateral and clearing the latch until an LKAS press
(00000057--b294eba736 seg 24 50.2 s).
"""
from types import SimpleNamespace
from typing import cast

import pytest

from opendbc.car import gen_empty_fingerprint, structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.cereal import log
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.selfdrive.selfdrived.selfdrived import SelfdriveD
from openpilot.starpilot.aol.intent import AolSettings, AOL_TOGGLE
from openpilot.starpilot.aol.runtime import AxisDecision
from openpilot.starpilot.aol.wire import IntentState, PandaSlot, SafetyState


class Messages(dict):
  def all_checks(self, services=None):
    return True


def _cp():
  fingerprint = gen_empty_fingerprint()
  fingerprint[0][0x201] = 6
  cp = CarInterface.get_params(CAR.HONDA_CLARITY, fingerprint, [], False, False, False)
  cp.alternativeExperience = 32
  return cp


@pytest.mark.parametrize('pause_mps,v_ego,lateral', [
  (0.0, -0.003, True),   # setting off: a stopped car's negative speed noise is not "below 0"
  (0.0, 0.0, True),
  (0.0, 5.0, True),
  (2.0, 1.0, False),     # setting on: braking below the pause speed still pauses
  (2.0, -0.003, False),
  (2.0, 5.0, True),
])
def test_brake_at_stop_keeps_lateral_unless_pause_is_set(pause_mps, v_ego, lateral):
  now = 4_000_000_000
  cp = _cp()
  config = cp.safetyConfigs[-1]
  model, word = int(config.safetyModel.raw), int(config.safetyParam)
  intent = IntentState('card', 1, now, now, now + 200_000_000, True, False, False, True, True)
  slot = PandaSlot(0, 'panda', model, word, cp.alternativeExperience)
  native = SafetyState(1, True, now, now + 200_000_000, model, word, True, False, True, False,
                       'panda', 'axis', now, (slot,))
  cs = structs.CarState(canValid=True, gearShifter='drive', vEgo=v_ego, brakePressed=True, standstill=False)
  cs.cruiseState.available = True
  sm = Messages(driverMonitoringState=SimpleNamespace(alertLevel=0, lockout=False, alwaysOnLockout=False),
                extrinsicsCalibration=SimpleNamespace(calStatus=log.ExtrinsicsCalibration.Status.calibrated))
  sd = SimpleNamespace(CP=cp, active=False, enabled=False, initialized=True, sm=sm,
                       aol_settings=AolSettings(True, pause_mps, AOL_TOGGLE, 0, (0, 0, 0), (0, 0, 0)),
                       aol_axis_decision=AxisDecision(lateral_active=True, native_acknowledged=True),
                       aol_car_state_log_ns=now, aol_session_id='axis', aol_dm_lateral_inhibit=False,
                       nostalgia_paddle_cancel=False, events=Events(), car_state_samples=((cs, True),))
  result = SelfdriveD._decide_aol_axes(cast(SelfdriveD, sd), cs, intent, native, now_ns=now)
  assert result.desired_lateral == lateral
  assert result.lateral_active == lateral
