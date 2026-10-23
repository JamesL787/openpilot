import json
import os
import tempfile
from types import SimpleNamespace

import pytest

from openpilot.starpilot.lateral.lane_change_preferences import LaneChangePolicy, LiveLaneChangePolicy, decode, to_value


def sgsp(guidance=True, **extra):
  # SGSP's version 5: turnSignalGuidance in place of our turnDesires / turnDesireSpeedMps
  document = to_value(LaneChangePolicy())
  document.update(version=5, turnSignalGuidance=guidance, **extra)
  document.pop("turnDesires", None)
  document.pop("turnDesireSpeedMps", None)
  return document


def ours(turn=True, speed=6.7):
  return {**to_value(LaneChangePolicy()), "version": 5, "turnDesires": turn, "turnDesireSpeedMps": speed}


@pytest.mark.parametrize("guidance", (True, False))
def test_a_document_in_sgsps_version_5_reads_and_keeps_force_turn_desires_off(guidance):
  policy = decode(json.dumps(sgsp(guidance)).encode())
  assert policy is not None and policy.enabled and not policy.turn_desires


@pytest.mark.parametrize("turn", (True, False))
def test_our_version_5_document_still_reads(turn):
  policy = decode(json.dumps(ours(turn)).encode())
  assert policy is not None and policy.turn_desires is turn and policy.turn_desire_speed_mps == 6.7


@pytest.mark.parametrize("shape", (sgsp, ours))
def test_lane_change_assist_is_not_disabled_by_either_shape(shape):
  with tempfile.TemporaryDirectory() as root:
    path = os.path.join(root, "LaneChangePreferences")
    raw = json.dumps(shape()).encode()
    with open(path, "wb") as handle:
      handle.write(raw)
    live = LiveLaneChangePolicy(SimpleNamespace(get_param_path=lambda key: path))
    assert live.requested.enabled
    with open(path, "rb") as handle:
      assert handle.read() == raw  # not rewritten on read


def test_other_shapes_stay_rejected():
  for bad in (sgsp(1), sgsp("yes"), sgsp(bogus=1), {**sgsp(), "turnDesires": True}, {**ours(), "turnSignalGuidance": True},
              {**ours(), "turnDesireSpeedMps": float("inf")}):
    assert decode(json.dumps(bad).encode()) is None
  missing = sgsp()
  del missing["turnSignalGuidance"]
  assert decode(json.dumps(missing).encode()) is None
