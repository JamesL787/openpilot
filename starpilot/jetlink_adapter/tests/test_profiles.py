"""The external model identity gate: only a model this fork validated may reach the parser."""
import copy
from pathlib import Path

import pytest

from jetlink.spec import ModelSpec
from openpilot.starpilot.jetlink_adapter import profiles
from openpilot.starpilot.jetlink_adapter.profiles import CINQUE_TERRE_V3 as P

CACHED_ONNX = Path.home() / "Library/Caches/jetlink/models" / f"{P.sha256[:16]}.onnx"


def spec(**changes) -> ModelSpec:
  fields = dict(sha256=P.sha256, nbytes=P.nbytes, frame_skip=P.frame_skip,
                input_shapes=dict(P.input_shapes), output_shapes=dict(P.output_shapes),
                output_slices={k: slice(*v) for k, v in P.output_slices.items()}, checkpoint=None)
  fields.update(changes)
  return ModelSpec(**fields)


def test_the_pinned_model_is_accepted_and_carries_its_generation():
  profile = profiles.require_profile(spec())
  assert profile is P
  assert (profile.is_v16, profile.is_v15, profile.is_v14, profile.is_v9) == (True, False, False, False)
  assert profile.mlsim is True


@pytest.mark.parametrize("change", [
  {"sha256": "0" * 64},
  {"nbytes": P.nbytes + 1},
  {"frame_skip": 1},
  {"input_shapes": {**P.input_shapes, "action_t": (1, 3)}},
  {"input_shapes": {k: v for k, v in P.input_shapes.items() if k != "state_feat_q"}},
  {"output_shapes": {**P.output_shapes, "outputs": (1, 18453)}},
])
def test_any_difference_from_the_validated_model_is_refused(change):
  with pytest.raises(profiles.UnsupportedModel):
    profiles.require_profile(spec(**change))


def test_a_moved_output_head_is_refused_and_named():
  slices = {k: slice(*v) for k, v in P.output_slices.items()}
  slices["action"] = slice(2062, 2068)
  with pytest.raises(profiles.UnsupportedModel, match="action"):
    profiles.require_profile(spec(output_slices=slices))


def test_a_missing_head_is_refused():
  slices = {k: slice(*v) for k, v in P.output_slices.items() if k != "plan"}
  with pytest.raises(profiles.UnsupportedModel, match="plan"):
    profiles.require_profile(spec(output_slices=slices))


def test_the_profile_is_not_mutable_through_a_spec():
  before = copy.deepcopy(P.output_slices)
  profiles.require_profile(spec())
  assert P.output_slices == before


def test_every_head_modeld_parses_is_present():
  # fill_model_msg / get_action_from_model read these from the parsed output
  assert {"plan", "action", "lane_lines", "road_edges", "lead", "lead_prob", "meta", "desire_state", "pose",
          "wide_from_device_euler", "road_transform", "hidden_state"} <= set(P.output_slices)


@pytest.mark.skipif(not CACHED_ONNX.is_file(), reason="Cinque Terre V3 ONNX not in the Jetlink cache on this machine")
def test_the_profile_matches_the_real_onnx():
  """The numbers in profiles.py were read off this file; this proves the file still says them."""
  from jetlink.spec import spec_from_onnx
  real = spec_from_onnx(str(CACHED_ONNX), frame_skip=P.frame_skip, sha256=P.sha256, nbytes=CACHED_ONNX.stat().st_size)
  assert real.nbytes == P.nbytes
  assert profiles.require_profile(real) is P


FAMILY = [p for p in profiles.PROFILES.values() if p is not P]


def test_the_catalog_family_is_pinned_by_its_own_hash_and_size_and_none_collide():
  assert len(FAMILY) == 5
  assert len(profiles.PROFILES) == 6 and len({p.ref for p in profiles.PROFILES.values()}) == 6
  assert all(len(p.sha256) == 64 and len(p.ref) == 40 and p.nbytes != P.nbytes for p in FAMILY)


@pytest.mark.parametrize("profile", FAMILY, ids=lambda p: p.name)
def test_a_family_model_is_accepted_only_with_cinque_terre_v3s_exact_layout(profile):
  ok = spec(sha256=profile.sha256, nbytes=profile.nbytes)
  assert profiles.require_profile(ok) is profile and profile.is_v16
  # the layout is assumed, not read from the ONNX: a server reporting anything else must be refused
  moved = {**{k: slice(*v) for k, v in P.output_slices.items()}, "action": slice(2062, 2067)}
  with pytest.raises(profiles.UnsupportedModel):
    profiles.require_profile(spec(sha256=profile.sha256, nbytes=profile.nbytes, output_slices=moved))
  with pytest.raises(profiles.UnsupportedModel):
    profiles.require_profile(spec(sha256=profile.sha256, nbytes=profile.nbytes + 1))
