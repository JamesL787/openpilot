from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from openpilot.common.params import Params
from openpilot.starpilot.galaxy.localization_settings import LocalizationSettingsOwner
from openpilot.starpilot.galaxy.settings import AuthorityContext, ContextSource, SettingsChanged, SettingsGateway
from openpilot.starpilot.speed_limits import offset_document as od
from openpilot.starpilot.ui.feature_settings_state import FeatureSettingsRequest
from openpilot.starpilot.ui.slc_offset_feature import DOCUMENT_KEY


def test_real_gateway_units_and_wheel_side_without_a_vehicle(tmp_path):
  params = Params(str(tmp_path))
  context = SimpleNamespace(value=AuthorityContext(True, None, None))
  context.sample = lambda: context.value
  gateway = SettingsGateway(params, cast(ContextSource, context))
  token, generation = "localization-session", b"generation"

  def preview(index, value):
    page = gateway.page("localization", token, generation)
    assert page["title"] == "Localization" and not page["vehicleIdentified"]
    assert [row["label"] for row in page["rows"]] == ["Use Kilometers (km/h)", "Right-Hand Drive"]
    return gateway.preview(page["view"], index, 0, token, generation, value=value)["intent"]

  assert gateway.confirm(preview(0, "On"), token, generation)
  assert params.get_bool("IsMetric")
  assert not Path(params.get_param_path(DOCUMENT_KEY)).exists()
  assert gateway.confirm(preview(1, "On"), token, generation)
  assert params.get_bool("IsRhdDetected") and params.get_bool("OnroadCycleRequested")
  pending = preview(1, "Off")
  context.value = replace(context.value, parked=False)
  with pytest.raises(SettingsChanged):
    gateway.confirm(pending, token, generation)
  assert params.get_bool("IsRhdDetected")


def test_localization_preserves_offsets_and_legacy_values(tmp_path):
  params = Params(str(tmp_path))
  params.put_bool("IsMetric", False, block=True)
  params.put("Offset1", 5.0, block=True)
  params.put_bool("SpeedLimitController", False, block=True)
  owner = LocalizationSettingsOwner(params, lambda: True, lambda: True)
  assert owner.apply(FeatureSettingsRequest("IsMetric", b"0", "On"))
  document = od.decode(Path(params.get_param_path(DOCUMENT_KEY)).read_bytes())
  assert document == od.adopt_legacy(False, (5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0))
  assert Path(params.get_param_path("Offset1")).read_bytes() == b"5.0"
  assert owner.apply(FeatureSettingsRequest("IsMetric", b"1", "Off"))
  assert od.decode(Path(params.get_param_path(DOCUMENT_KEY)).read_bytes()) == document


@pytest.mark.parametrize("condition", ["onroad", "preview", "unauthorized", "stale", "invalid"])
def test_wheel_side_cannot_change_during_a_drive_or_stale_request(tmp_path, condition):
  params = Params(str(tmp_path))
  params.put_bool("IsRhdDetected", False, block=True)
  params.put_bool("IsDriverViewEnabled", condition == "preview", block=True)
  owner = LocalizationSettingsOwner(params, lambda: condition != "unauthorized", lambda: condition != "onroad")
  request = FeatureSettingsRequest("IsRhdDetected", b"1" if condition == "stale" else b"0",
                                   "invalid" if condition == "invalid" else "On")
  assert not owner.apply(request)
  assert not params.get_bool("IsRhdDetected")
  assert not params.get_bool("OnroadCycleRequested")


def test_settings_session_rechecked_before_localization_commit(tmp_path):
  params = Params(str(tmp_path))
  context = SimpleNamespace(sample=lambda: AuthorityContext(True, None, None))
  gateway = SettingsGateway(params, cast(ContextSource, context))
  page = gateway.page("localization", "session", b"generation")
  pending = gateway.preview(page["view"], 1, 0, "session", b"generation", value="On")["intent"]
  with pytest.raises(SettingsChanged):
    gateway.confirm(pending, "session", b"generation", session_valid=lambda: False)
  assert not params.get_bool("IsRhdDetected")


def test_units_without_offsets_work_onroad_but_wheel_side_waits(tmp_path):
  params = Params(str(tmp_path))
  owner = LocalizationSettingsOwner(params, lambda: True, lambda: False)
  rows = owner.snapshot().rows
  assert rows[0].available and not rows[1].available
  assert owner.apply(FeatureSettingsRequest("IsMetric", None, "On"))
  assert params.get_bool("IsMetric")
  assert not Path(params.get_param_path(DOCUMENT_KEY)).exists()


def test_legacy_offsets_explain_the_one_time_park_requirement(tmp_path):
  params = Params(str(tmp_path))
  params.put("Offset1", 5.0, block=True)
  owner = LocalizationSettingsOwner(params, lambda: True, lambda: False)
  row = owner.snapshot().rows[0]
  assert not row.available and "Park once" in row.reason
  assert not owner.apply(FeatureSettingsRequest("IsMetric", None, "On"))
  assert not params.get_bool("IsMetric")
