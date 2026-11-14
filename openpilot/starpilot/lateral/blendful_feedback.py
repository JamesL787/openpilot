"""Blendful state transport.

``feedback_message`` builds the ``starpilotBlendfulState`` event modeld
publishes each frame. The onroad drawing lives in
``openpilot.starpilot.ui.blendful_renderer`` so this module stays importable
from the realtime modeld process. A port of sunnypilot's Blendful state
logging (sunnypilot/sunnypilot PR #2073).
"""

from openpilot.cereal import messaging

SERVICE = 'starpilotBlendfulState'
VERSION = 1


def feedback_message(blendful, *, model_valid: bool, model_mono_time: int):
  event = messaging.new_message(SERVICE, valid=model_valid)
  state = event.starpilotBlendfulState
  state.version = VERSION
  state.curvature = float(blendful.curvature)
  state.trust = float(blendful.trust)
  state.modelCurvature = float(blendful.model_curvature)
  state.goingAround = bool(blendful.going_around)
  state.leftProb = float(blendful.l_prob)
  state.rightProb = float(blendful.r_prob)
  state.laneWidth = float(blendful.lane_width.x)
  state.modelMonoTime = model_mono_time
  return event


def lateral_active(sm) -> bool:
  return bool(sm.valid['carControl'] and sm['carControl'].latActive)
