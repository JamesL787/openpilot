#!/usr/bin/env python3
import json
import os
import time

from openpilot.system.hardware import TICI
from openpilot.common.realtime import Priority, config_realtime_process, set_core_affinity
from openpilot.common.swaglog import cloudlog
from openpilot.common.watchdog import kick_watchdog
from openpilot.system.ui.lib.application import gui_app
from openpilot.selfdrive.ui.stall_monitor import UIStallMonitor
from openpilot.selfdrive.ui.ui_state import ui_state

BIG_UI = gui_app.big_ui()
STREAM_TELEMETRY_PERIOD = 0.5  # at most 2 Hz, only while a browser polls /telemetry
STREAM_REQUEST_PERIOD = 0.5  # at most 2 Hz; Galaxy sets UiStreamRequested when Live UI opens
STREAM_STATE_SCHEMA = 1


def _stall_context() -> dict[str, object]:
  active_widget = gui_app.get_active_widget()
  context = {
    "ui_mode": "big" if BIG_UI else "small",
    "started": ui_state.started,
    "ignition": ui_state.ignition,
    "engaged": ui_state.engaged,
    "render_frame": gui_app.frame,
    "ui_state_frame": ui_state.sm.frame,
    "target_fps": gui_app.target_fps,
    "active_widget": type(active_widget).__name__ if active_widget is not None else "none",
    "frame_timing": gui_app.frame_timing._asdict(),
  }

  try:
    device_state = ui_state.sm["deviceState"]
    context.update({
      "device_state_valid": bool(ui_state.sm.valid["deviceState"]),
      "memory_usage_percent": int(device_state.memoryUsagePercent),
      "gpu_usage_percent": int(device_state.gpuUsagePercent),
      "max_cpu_usage_percent": max((int(value) for value in device_state.cpuUsagePercent), default=0),
      "max_cpu_temp_c": round(max((float(value) for value in device_state.cpuTempC), default=0.0), 1),
      "max_gpu_temp_c": round(max((float(value) for value in device_state.gpuTempC), default=0.0), 1),
      "thermal_status": str(device_state.thermalStatus),
    })
  except Exception:
    pass

  return context


def main():
  cores = {5, }
  config_realtime_process(0, Priority.UI)

  stall_monitor = UIStallMonitor("raylib_ui")
  stall_monitor.progress("ui.before_init_window")
  stall_monitor.start()

  stream_state_payload: dict[str, object] | None = None
  stream_state_sequence = 0

  def publish_stream_state() -> None:
    """Publish real streamer readiness for Galaxy, on change only.

    Clearing UiStreamRequested only proves the request was seen. The viewer
    page is served *by* the listener, so Galaxy waits for "running" here before
    loading it, and "error" carries the reason a start failed. `sequence` lets
    the page tell a fresh failure from a stale one.
    """
    nonlocal stream_state_payload, stream_state_sequence
    state, detail, port = gui_app.ui_stream_state()
    payload: dict[str, object] = {"state": state, "detail": detail, "port": port}
    if payload == stream_state_payload:
      return
    stream_state_payload = payload
    stream_state_sequence += 1
    ui_state.params_memory.put("UiStreamState", json.dumps(
      {"schemaVersion": STREAM_STATE_SCHEMA, "sequence": stream_state_sequence, **payload}))

  try:
    ui_state.ui_params.start()
    ui_state.live_params.start()
    gui_app.init_window("UI")
    stall_monitor.progress("ui.after_init_window")
    gui_app.set_progress_hook(stall_monitor.progress)
    kick_watchdog()
    stall_monitor.progress("ui.before_layout_init")
    if BIG_UI:
      from openpilot.selfdrive.ui.layouts.main import MainLayout
      MainLayout()
    else:
      from openpilot.selfdrive.ui.mici.layouts.main import MiciMainLayout
      MiciMainLayout()
    stall_monitor.progress("ui.after_layout_init")
    stall_monitor.set_context(_stall_context())
    kick_watchdog()
    stall_monitor.progress("ui.loop_ready")
    context_update_time = 0.0
    stream_telemetry_builder = None
    last_stream_telemetry = 0.0
    last_stream_request_check = 0.0
    for should_render in gui_app.render():
      stall_monitor.progress("ui.loop_iteration")
      kick_watchdog()
      stall_monitor.progress("ui.after_watchdog")
      ui_state.update(progress_hook=stall_monitor.progress)
      stall_monitor.progress("ui.after_state_update")
      now = time.monotonic()
      # Remote taps from Live UI are for setting things up while parked. Never
      # while driving: someone off the car must not change it under the driver.
      gui_app.set_ui_stream_control(not ui_state.started, "the car is onroad")

      # Live UI in Galaxy posts UiStreamRequested. It is consumed whether or
      # not the start succeeds — a stuck flag would re-request every tick — and
      # readiness is reported separately through UiStreamState, which is what
      # the page actually waits on. Reuses ui_state's memory Params.
      if now - last_stream_request_check >= STREAM_REQUEST_PERIOD:
        last_stream_request_check = now
        try:
          if ui_state.params_memory.get_bool("UiStreamRequested"):
            ui_state.params_memory.remove("UiStreamRequested")
            gui_app.request_ui_stream()
          publish_stream_state()
        except Exception as exc:
          cloudlog.error(f"UI streamer request check failed: {exc}")

      # Demand-gated telemetry: imported and built only while a browser polls.
      if gui_app.stream_telemetry_due(now) and now - last_stream_telemetry >= STREAM_TELEMETRY_PERIOD:
        last_stream_telemetry = now
        try:
          if stream_telemetry_builder is None:
            from openpilot.selfdrive.ui.ui_stream_telemetry import build_for_ui_state
            stream_telemetry_builder = build_for_ui_state
          gui_app.publish_stream_telemetry(stream_telemetry_builder(ui_state, now=now, big_ui=BIG_UI))
        except Exception as exc:
          cloudlog.error(f"UI streamer telemetry failed: {exc}")

      if now - context_update_time >= 1.0:
        stall_monitor.set_context(_stall_context())
        context_update_time = now
      if should_render:
        # reaffine after power save offlines our core
        if TICI and os.sched_getaffinity(0) != cores:
          try:
            set_core_affinity(list(cores))
          except OSError:
            pass
      stall_monitor.progress("ui.loop_idle")
  finally:
    gui_app.stop_ui_stream()
    # The listener is gone with the UI: say so, or Galaxy would keep loading a
    # viewer page that nothing serves.
    try:
      publish_stream_state()
    except Exception as exc:
      cloudlog.error(f"UI streamer state publish failed: {exc}")
    gui_app.set_progress_hook(None)
    ui_state.live_params.stop()
    ui_state.ui_params.stop()
    stall_monitor.stop()


if __name__ == "__main__":
  main()
