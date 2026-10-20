import json
from dataclasses import replace

from openpilot.common.constants import CV
from openpilot.starpilot.lateral.lane_change_preferences import LaneChangePolicy, decode, to_value


def test_turn_desires_roundtrip_and_older_documents_keep_them_off():
  policy = replace(LaneChangePolicy(), turn_desires=True, turn_desire_speed_mps=12 * CV.MPH_TO_MS)
  raw = json.dumps(to_value(policy)).encode()
  assert json.loads(raw)["version"] == 5
  assert decode(raw) == policy
  default = to_value(LaneChangePolicy())
  assert default["version"] == 4 and "turnDesires" not in default
  assert decode(json.dumps(default).encode()) == LaneChangePolicy()
  turned_off = to_value(replace(policy, turn_desires=False))
  assert turned_off["version"] == 5 and decode(json.dumps(turned_off).encode()).turn_desire_speed_mps == 12 * CV.MPH_TO_MS
  assert not LaneChangePolicy().turn_desires
  assert LaneChangePolicy().turn_desire_speed_mps == 15 * CV.MPH_TO_MS


def test_turn_desire_document_rejects_bad_values():
  good = to_value(replace(LaneChangePolicy(), turn_desires=True))
  for field, value in (("turnDesires", 1), ("turnDesireSpeedMps", 4 * CV.MPH_TO_MS), ("turnDesireSpeedMps", 31 * CV.MPH_TO_MS),
                       ("turnDesireSpeedMps", "15")):
    assert decode(json.dumps(good | {field: value}).encode()) is None
  missing = dict(good)
  del missing["turnDesireSpeedMps"]
  assert decode(json.dumps(missing).encode()) is None
