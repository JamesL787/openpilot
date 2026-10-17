"""WeakLeadCapEase toggle (WEAK_LEAD_CAP_EASE_* in longitudinal_planner.py). Static tests; the slew itself is replay evidence."""
import json
from pathlib import Path
from types import SimpleNamespace

from openpilot.selfdrive.controls.lib import longitudinal_planner as lp

ROOT = Path(__file__).resolve().parents[3]


def _rlead(tid, d, a=0.0, radar=True, status=True):
  return SimpleNamespace(status=status, radar=radar, radarTrackId=tid, dRel=d, vLead=1.0, vRel=0.0, yRel=0.0, aLeadK=a, modelProb=1.0)


def _none():
  return SimpleNamespace(status=False, radar=False)


def _sm(model_a, prob=0.95):
  return {'carState': SimpleNamespace(aEgo=0.0),
          'modelV2': SimpleNamespace(leadsV3=[SimpleNamespace(prob=prob, a=[model_a])])}


def _planner():
  p = object.__new__(lp.LongitudinalPlanner)
  p.weak_lead_cap_newborn = lp.NewbornLeadHold()
  return p


def _step(p, one, sm, two=None):
  p.lead_one, p.lead_two = one, two or _none()
  return p.weak_lead_cap_ease_leads(sm)


def test_newborn_radar_lead_takes_model_accel_then_its_own_after_two_seconds():
  p = _planner()
  out = [float(_step(p, _rlead(5, 8.0), _sm(1.7))[0].aLeadK) for _ in range(lp.NEWBORN_LEAD_FRAMES + 3)]
  assert all(a == 1.7 for a in out[:lp.NEWBORN_LEAD_FRAMES])
  assert all(a == 0.0 for a in out[lp.NEWBORN_LEAD_FRAMES:])


def test_model_accel_only_raises_and_needs_a_confident_model_lead():
  p = _planner()
  assert float(_step(p, _rlead(5, 8.0, a=0.5), _sm(-1.0))[0].aLeadK) == 0.5   # model says slower: lead kept
  p = _planner()
  assert float(_step(p, _rlead(5, 8.0), _sm(1.7, prob=0.5))[0].aLeadK) == 0.0  # weak model lead: ignored


def test_vision_lead_and_other_fields_are_untouched():
  p = _planner()
  vis = _rlead(-1, 8.0, radar=False)
  assert _step(p, vis, _sm(1.7))[0] is vis
  bounded = _step(p, _rlead(6, 9.0), _sm(1.7))[0]
  assert (bounded.dRel, bounded.vLead, bounded.yRel) == (9.0, 1.0, 0.0)


def test_track_is_newborn_again_after_a_range_jump_or_a_gap():
  p = _planner()
  for _ in range(lp.NEWBORN_LEAD_FRAMES + 1):
    _step(p, _rlead(5, 8.0), _sm(1.7))
  assert float(_step(p, _rlead(5, 8.0), _sm(1.7))[0].aLeadK) == 0.0
  assert float(_step(p, _rlead(5, 8.0 + lp.NEWBORN_LEAD_JUMP_M + 1.0), _sm(1.7))[0].aLeadK) == 1.7
  for _ in range(lp.NEWBORN_LEAD_FRAMES + 1):
    _step(p, _rlead(5, 13.0), _sm(1.7))
  for _ in range(lp.NEWBORN_LEAD_GAP_FRAMES + 1):
    _step(p, _none(), _sm(1.7))
  assert float(_step(p, _rlead(5, 13.0), _sm(1.7))[0].aLeadK) == 1.7


def test_newborn_lead_hold_bound_unchanged_by_observe_refactor():
  hold = lp.NewbornLeadHold()
  hold.tick()
  assert hold.bound(_rlead(7, 60.0, a=-3.0), 0.0) == -lp.NEWBORN_LEAD_MIN_BRAKE
  assert hold.is_newborn(_rlead(7, 60.0))
  assert hold.bound(_rlead(7, 60.0, a=-0.5), 0.0) is None


def test_slew_is_gated_and_positive_only():
  src = Path(lp.__file__).read_text()
  assert lp.WEAK_LEAD_CAP_EASE_JERK == 2.0
  assert 'self.weak_lead_cap_ease = bool(getattr(starpilot_toggles, "weak_lead_cap_ease", False))' in src
  assert "max(low_speed_weak_lead_accel_cap, prev_output_a_target - weak_lead_cap_step)" in src
  assert "release_limit = max(prev_output_a_target, 0.0) + weak_lead_cap_step" in src


def test_toggle_is_wired_and_off_by_default():
  found = []

  def walk(node):
    if isinstance(node, dict):
      if node.get("key") == "WeakLeadCapEase":
        found.append(node)
      for v in node.values():
        walk(v)
    elif isinstance(node, list):
      for v in node:
        walk(v)
  walk(json.loads((ROOT / "starpilot/common/assets/device_settings_layout.json").read_text()))
  assert len(found) == 1
  assert found[0]["parent_key"] == "AdvancedLongitudinalTune" and found[0]["ui_type"] == "toggle"
  assert 'SettingRow("WeakLeadCapEase", "toggle"' in (ROOT / "selfdrive/ui/layouts/settings/starpilot/longitudinal.py").read_text()
  assert '{"WeakLeadCapEase", {PERSISTENT, BOOL, "0", "0", 3}}' in (ROOT / "common/params_keys.h").read_text()
  assert 'toggle.weak_lead_cap_ease = False' in (ROOT / "starpilot/common/starpilot_variables.py").read_text()
