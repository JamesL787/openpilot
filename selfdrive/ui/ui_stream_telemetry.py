"""Primitive telemetry snapshot for the UI streamer.

This is a pure builder over the existing UI ``SubMaster``. It creates no new
subscription, no ``Params`` instance and no cereal reader that could cross a
thread boundary. The UI thread calls it at most 2 Hz while a browser is
actively polling ``/telemetry``.

Semantics deliberately mirror the on-device HUD:

* ``setSpeed`` follows the selected BIG/MICI set-speed branch, including the
  StarPilot set-speed offset (BIG only) and display units.
* ``engaged`` is ``started and selfdriveState.enabled``; vehicle cruise
  (``carState.cruiseState.enabled``) is reported separately and never used to
  infer openpilot engagement.
* Stale or offroad sources clear their driving fields instead of resurfacing
  old values.
* ``grade`` is null: the current UI subscriptions have no verified livePose
  pitch source, so it is not labelled as road grade.
"""

from __future__ import annotations

import json
import math

SCHEMA_VERSION = 1

DRIVING_MAX_AGE = 2.0
DEVICE_MAX_AGE = 5.0
KM_TO_MILE = 0.621371
SET_SPEED_NA = 255.0


def _finite(value) -> float | None:
  try:
    result = float(value)
  except (TypeError, ValueError, AttributeError):
    return None
  return result if math.isfinite(result) else None


def _round(value: float | None, digits: int) -> float | None:
  return None if value is None else round(value, digits)


def _message(sm, name: str, now: float, max_age: float):
  """Return a fresh, valid message or ``None``."""
  try:
    if not (sm.alive.get(name, False) and sm.valid.get(name, False)):
      return None
    received = sm.recv_time.get(name, 0.0)
    if not received or (now - received) > max_age:
      return None
    return sm[name]
  except Exception:
    return None


def _source_status(sm, name: str, now: float, max_age: float) -> dict[str, object]:
  try:
    received = sm.recv_time.get(name, 0.0)
    age = (now - received) if received else None
    available = bool(sm.alive.get(name, False) and sm.valid.get(name, False)
                     and age is not None and age <= max_age)
  except Exception:
    age, available = None, False
  return {"ageMs": None if age is None else round(age * 1000), "available": available}


def _max_finite(values, digits: int) -> float | None:
  finite = [v for v in (_finite(x) for x in values) if v is not None]
  if not finite:
    return None
  return _round(max(finite), digits)


def _mean_finite(values, digits: int) -> float | None:
  finite = [v for v in (_finite(x) for x in values) if v is not None]
  if not finite:
    return None
  return _round(sum(finite) / len(finite), digits)


def _set_speed(car_state, controls_state, *, is_metric: bool, big_ui: bool,
               set_speed_offset: float) -> float | None:
  # BIG applies set_speed_offset; MICI does not. Both apply KM_TO_MILE when
  # imperial (MICI does it at draw time, BIG in state), so do not "unify" the
  # conversion away — only the offset differs.
  try:
    v_cruise_cluster = _finite(car_state.vCruiseCluster) or 0.0
  except Exception:
    return None

  if v_cruise_cluster != 0.0:
    v_cruise = v_cruise_cluster
  elif controls_state is not None:
    try:
      v_cruise = _finite(controls_state.vCruiseDEPRECATED)
    except Exception:
      return None
  else:
    # No cluster set-speed and no controlsState to fall back to.
    return None

  if v_cruise is None or not (0 < v_cruise < SET_SPEED_NA):
    return None

  value = v_cruise + (set_speed_offset if big_ui else 0.0)
  if not is_metric:
    value *= KM_TO_MILE
  return _round(value, 1)


def build_telemetry(sm, *, now: float, is_metric: bool, started: bool, big_ui: bool,
                    set_speed_offset: float = 0.0) -> bytes:
  """Return a JSON telemetry payload. Values that are unavailable are null."""
  now = float(now)
  set_speed_offset = _finite(set_speed_offset) or 0.0

  car_state = _message(sm, "carState", now, DRIVING_MAX_AGE)
  selfdrive_state = _message(sm, "selfdriveState", now, DRIVING_MAX_AGE)
  radar_state = _message(sm, "radarState", now, DRIVING_MAX_AGE)
  controls_state = _message(sm, "controlsState", now, DRIVING_MAX_AGE)
  model_state = _message(sm, "modelV2", now, DRIVING_MAX_AGE)
  device_state = _message(sm, "deviceState", now, DEVICE_MAX_AGE)

  v_ego = a_ego = None
  brake = brake_pressed = gas_pressed = None
  cruise_enabled = None
  if started and car_state is not None:
    try:
      v_ego = _round(_finite(car_state.vEgo), 2)
      a_ego = _round(_finite(car_state.aEgo), 2)
      raw_brake = _finite(car_state.brake)
      brake = None if raw_brake is None else _round(min(100.0, max(0.0, raw_brake * 100.0)), 1)
      brake_pressed = bool(car_state.brakePressed)
      gas_pressed = bool(car_state.gasPressed)
      cruise_enabled = bool(car_state.cruiseState.enabled)
    except Exception:
      pass

  drive_state = None
  engaged = False
  if started and selfdrive_state is not None:
    try:
      drive_state = str(selfdrive_state.state)
      engaged = bool(selfdrive_state.enabled)
    except Exception:
      drive_state = None
      engaged = False

  set_speed = None
  if started and car_state is not None:
    set_speed = _set_speed(car_state, controls_state, is_metric=is_metric, big_ui=big_ui,
                          set_speed_offset=set_speed_offset)

  lead_dist = None
  if started and radar_state is not None:
    try:
      lead = radar_state.leadOne
      if lead.status:
        lead_dist = _round(_finite(lead.dRel), 1)
    except Exception:
      lead_dist = None

  cpu_temp = cpu_usage = mem_used = None
  if device_state is not None:
    try:
      cpu_temp = _max_finite(device_state.cpuTempC, 1)
    except Exception:
      cpu_temp = None
    try:
      cpu_usage = _mean_finite(device_state.cpuUsagePercent, 1)
    except Exception:
      cpu_usage = None
    try:
      mem_used = _round(_finite(device_state.memoryUsagePercent), 0)
    except Exception:
      mem_used = None

  model_exec_ms = frame_drop = None
  if model_state is not None:
    try:
      raw_exec = _finite(model_state.modelExecutionTime)
      model_exec_ms = None if raw_exec is None else _round(raw_exec * 1000.0, 1)
    except Exception:
      model_exec_ms = None
    try:
      frame_drop = _round(_finite(model_state.frameDropPerc), 1)
    except Exception:
      frame_drop = None

  sources = {
    name: _source_status(sm, name, now, max_age)
    for name, max_age in (
      ("carState", DRIVING_MAX_AGE),
      ("selfdriveState", DRIVING_MAX_AGE),
      ("radarState", DRIVING_MAX_AGE),
      ("controlsState", DRIVING_MAX_AGE),
      ("modelV2", DRIVING_MAX_AGE),
      ("deviceState", DEVICE_MAX_AGE),
    )
  }

  payload = {
    "schemaVersion": SCHEMA_VERSION,
    "sampledAtMonotonicMs": round(now * 1000),
    "isMetric": bool(is_metric),
    "started": bool(started),
    "sources": sources,
    "vEgo": v_ego,
    "aEgo": a_ego,
    "setSpeed": set_speed,
    "setSpeedUnit": "km/h" if is_metric else "mph",
    "driveState": drive_state,
    "engaged": engaged,
    "cruiseEnabled": cruise_enabled,
    "leadDist": lead_dist,
    "brake": brake,
    "brakePressed": brake_pressed,
    "gasPressed": gas_pressed,
    "cpuTempC": cpu_temp,
    "cpuUsagePercent": cpu_usage,
    "memoryUsagePercent": mem_used,
    "modelExecMs": model_exec_ms,
    "frameDropPerc": frame_drop,
    "grade": None,
  }
  return json.dumps(payload, allow_nan=False).encode()


def build_for_ui_state(ui_state, *, now: float, big_ui: bool) -> bytes:
  """Convenience wrapper for the UI loop. Reads only existing UI-state fields."""
  try:
    toggles = ui_state.starpilot_toggles
  except Exception:
    toggles = {}
  offset = 0.0
  try:
    offset = float(toggles.get("set_speed_offset", 0.0) or 0.0)
  except (AttributeError, TypeError, ValueError):
    offset = 0.0

  return build_telemetry(
    ui_state.sm,
    now=now,
    is_metric=bool(getattr(ui_state, "is_metric", True)),
    started=bool(getattr(ui_state, "started", False)),
    big_ui=big_ui,
    set_speed_offset=offset,
  )
