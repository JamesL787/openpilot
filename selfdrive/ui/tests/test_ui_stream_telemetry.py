import json
import math
from types import SimpleNamespace

from openpilot.selfdrive.ui.ui_stream_telemetry import build_for_ui_state, build_telemetry


class FakeSM:
  """Minimal SubMaster stand-in covering the fields the builder reads."""

  def __init__(self, data, *, now, valid=None, alive=None, ages=None):
    self._data = data
    self.frame = 1
    self.valid = dict.fromkeys(data, True)
    self.alive = dict.fromkeys(data, True)
    self.recv_time = {name: now - (ages or {}).get(name, 0.0) for name in data}
    if valid:
      self.valid.update(valid)
    if alive:
      self.alive.update(alive)

  def __getitem__(self, name):
    return self._data[name]


def _car_state(**overrides):
  base = {
    "vEgo": 10.0, "aEgo": 1.5, "brake": 0.25, "brakePressed": False, "gasPressed": True,
    "vCruiseCluster": 100.0, "cruiseState": SimpleNamespace(enabled=True),
  }
  base.update(overrides)
  return SimpleNamespace(**base)


def _selfdrive_state(state="enabled", enabled=True):
  return SimpleNamespace(state=state, enabled=enabled)


def _radar_state(status=True, d_rel=35.0):
  return SimpleNamespace(leadOne=SimpleNamespace(status=status, dRel=d_rel))


def _device_state(cpu_temp=(70.0, 80.0), cpu_usage=(10, 20, 30), mem=42):
  return SimpleNamespace(cpuTempC=list(cpu_temp), cpuUsagePercent=list(cpu_usage), memoryUsagePercent=mem)


def _model_v2(exec_seconds=0.025, drops=3.5):
  return SimpleNamespace(modelExecutionTime=exec_seconds, frameDropPerc=drops)


def _sm(now, ages=None, valid=None, alive=None, **data):
  full = {
    "carState": _car_state(),
    "selfdriveState": _selfdrive_state(),
    "radarState": _radar_state(),
    "controlsState": SimpleNamespace(vCruiseDEPRECATED=100.0),
    "modelV2": _model_v2(),
    "deviceState": _device_state(),
  }
  full.update(data)
  return FakeSM(full, now=now, valid=valid, alive=alive, ages=ages)


def _build(sm, now=100.0, **kwargs):
  options = {"is_metric": True, "started": True, "big_ui": True}
  options.update(kwargs)
  return json.loads(build_telemetry(sm, now=now, **options))


def test_offroad_clears_driving_fields_but_keeps_device_metrics():
  sm = _sm(100.0)
  payload = _build(sm, started=False)
  assert payload["vEgo"] is None
  assert payload["aEgo"] is None
  assert payload["setSpeed"] is None
  assert payload["leadDist"] is None
  assert payload["brake"] is None
  assert payload["engaged"] is False
  assert payload["driveState"] is None
  assert payload["cruiseEnabled"] is None
  assert payload["cpuTempC"] == 80.0
  assert payload["cpuUsagePercent"] == 20.0
  assert payload["memoryUsagePercent"] == 42


def test_engagement_and_vehicle_cruise_are_independent():
  sm = _sm(100.0, selfdriveState=_selfdrive_state("overriding", enabled=False),
           carState=_car_state(cruiseState=SimpleNamespace(enabled=True)))
  payload = _build(sm)
  assert payload["driveState"] == "overriding"
  assert payload["engaged"] is False
  assert payload["cruiseEnabled"] is True


def test_engaged_requires_started():
  sm = _sm(100.0)
  payload = _build(sm, started=False)
  assert payload["engaged"] is False


def test_set_speed_big_metric_applies_offset():
  sm = _sm(100.0)
  payload = _build(sm, is_metric=True, big_ui=True, set_speed_offset=5.0)
  assert payload["setSpeed"] == 105.0
  assert payload["setSpeedUnit"] == "km/h"


def test_set_speed_big_imperial_converts_after_offset():
  sm = _sm(100.0)
  payload = _build(sm, is_metric=False, big_ui=True, set_speed_offset=5.0)
  assert payload["setSpeed"] == round(105.0 * 0.621371, 1)


def test_set_speed_mici_ignores_offset():
  sm = _sm(100.0)
  payload = _build(sm, is_metric=True, big_ui=False, set_speed_offset=5.0)
  assert payload["setSpeed"] == 100.0


def test_set_speed_falls_back_to_controls():
  sm = _sm(100.0, carState=_car_state(vCruiseCluster=0.0),
           controlsState=SimpleNamespace(vCruiseDEPRECATED=90.0))
  payload = _build(sm)
  assert payload["setSpeed"] == 90.0


def test_set_speed_sentinel_is_null():
  sm = _sm(100.0, carState=_car_state(vCruiseCluster=255.0))
  payload = _build(sm)
  assert payload["setSpeed"] is None


def test_set_speed_uses_cluster_without_fresh_controls_state():
  # controlsState is only needed when vCruiseCluster is 0.
  sm = _sm(100.0, controlsState=SimpleNamespace(vCruiseDEPRECATED=90.0),
           valid={"controlsState": False})
  assert _build(sm)["setSpeed"] == 100.0


def test_set_speed_null_without_cluster_or_controls_state():
  sm = _sm(100.0, carState=_car_state(vCruiseCluster=0.0),
           controlsState=SimpleNamespace(vCruiseDEPRECATED=0.0),
           valid={"controlsState": False})
  assert _build(sm)["setSpeed"] is None


def test_lead_distance_requires_status():
  assert _build(_sm(100.0))["leadDist"] == 35.0
  assert _build(_sm(100.0, radarState=_radar_state(status=False)))["leadDist"] is None


def test_brake_is_normalized_and_clamped():
  assert _build(_sm(100.0, carState=_car_state(brake=0.25)))["brake"] == 25.0
  assert _build(_sm(100.0, carState=_car_state(brake=1.5)))["brake"] == 100.0
  assert _build(_sm(100.0, carState=_car_state(brake=-0.5)))["brake"] == 0.0


def test_empty_device_arrays_are_null():
  sm = _sm(100.0, deviceState=_device_state(cpu_temp=(), cpu_usage=()))
  payload = _build(sm)
  assert payload["cpuTempC"] is None
  assert payload["cpuUsagePercent"] is None


def test_model_execution_seconds_to_ms_and_drop_percent():
  payload = _build(_sm(100.0))
  assert payload["modelExecMs"] == 25.0
  assert payload["frameDropPerc"] == 3.5


def test_stale_sources_are_unavailable_and_null():
  now = 100.0
  sm = _sm(now, ages={"carState": 5.0, "deviceState": 1.0})
  payload = _build(sm, now=now)
  assert payload["vEgo"] is None
  assert payload["sources"]["carState"]["available"] is False
  assert payload["sources"]["deviceState"]["available"] is True
  assert payload["cpuTempC"] == 80.0


def test_invalid_source_is_null():
  sm = _sm(100.0, valid={"carState": False})
  payload = _build(sm)
  assert payload["vEgo"] is None
  assert payload["sources"]["carState"]["available"] is False


def test_nonfinite_values_are_sanitized_and_json_is_strict():
  sm = _sm(100.0, carState=_car_state(vEgo=float("nan"), aEgo=float("inf")),
           modelV2=_model_v2(exec_seconds=float("nan")))
  payload = _build(sm)
  assert payload["vEgo"] is None
  assert payload["aEgo"] is None
  assert payload["modelExecMs"] is None
  # allow_nan=False would have raised for a leaked NaN; also assert Grade is null.
  assert payload["grade"] is None
  assert "NaN" not in build_telemetry(sm, now=100.0, is_metric=True, started=True, big_ui=True).decode()


def test_schema_and_metadata_fields():
  payload = _build(_sm(100.0), is_metric=False, started=True)
  assert payload["schemaVersion"] == 1
  assert payload["isMetric"] is False
  assert payload["started"] is True
  assert payload["sampledAtMonotonicMs"] == 100_000
  assert set(payload["sources"]) == {"carState", "selfdriveState", "radarState",
                                     "controlsState", "modelV2", "deviceState"}


def test_build_for_ui_state_reads_existing_fields():
  now = 100.0
  ui_state = SimpleNamespace(
    sm=_sm(now),
    is_metric=True,
    started=True,
    starpilot_toggles={"set_speed_offset": 5.0},
  )
  payload = json.loads(build_for_ui_state(ui_state, now=now, big_ui=True))
  assert payload["setSpeed"] == 105.0
  assert payload["engaged"] is True


def test_build_for_ui_state_tolerates_missing_toggles():
  now = 100.0
  ui_state = SimpleNamespace(sm=_sm(now), is_metric=True, started=True)
  payload = json.loads(build_for_ui_state(ui_state, now=now, big_ui=False))
  assert payload["setSpeed"] == 100.0
  assert not math.isnan(payload["setSpeed"])
