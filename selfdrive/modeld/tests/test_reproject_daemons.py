from pathlib import Path

import numpy as np
import pytest

from openpilot.selfdrive.modeld import modeld
from openpilot.system.manager.process_config import reproject as reproject_process
from openpilot.selfdrive.modeld.reproject_c4 import cameras, rotation
from openpilot.selfdrive.modeld.reproject_c4.meter import SeamMeter
from openpilot.selfdrive.modeld.reprojectcalibd import Fit, N_FRAMES, save_completed_rotation
from openpilot.selfdrive.modeld.reproject_config import REPROJECT_SESSION_PARAM, reproject_expected, select_reproject_session


class FakeClient:
  def __init__(self, frames):
    self.frames = iter(frames)
    self.frame_id = 0
    self.timestamp_sof = 0
    self.timestamp_eof = 0

  def recv(self):
    frame = next(self.frames, None)
    if frame is not None:
      self.frame_id, self.timestamp_sof = frame
      self.timestamp_eof = self.timestamp_sof + 1
      return frame
    return None


def test_recv_pair_uses_sof_not_equal_frame_ids():
  narrow = FakeClient([(44, 100_000_000)])
  wide = FakeClient([(12, 99_000_000)])

  pair = cameras.recv_pair(narrow, wide)

  assert pair == ((44, 100_000_000), (12, 99_000_000))


def test_recv_pair_logs_large_sof_delta_but_returns_pair(monkeypatch):
  logged = []
  monkeypatch.setattr(cameras.cloudlog, "error", lambda message: logged.append(message))
  narrow = FakeClient([(44, 100_000_000)])
  wide = FakeClient([(12, 80_000_000)])

  pair = cameras.recv_pair(narrow, wide)

  assert pair is not None
  assert len(logged) == 1


def test_table_cache_dir_imports_the_platform_hardware_module(monkeypatch):
  from openpilot.selfdrive.modeld.reproject_c4 import tables

  monkeypatch.setenv("XDG_CACHE_HOME", "/tmp/reproject-cache")
  assert tables.table_cache_dir() == "/tmp/reproject-cache"


def test_startup_rotation_requires_completed_fit(monkeypatch):
  class FakeParams:
    value = {"rotvec": [0.1, 0.2, 0.3]}

    def get(self, _key):
      return self.value

  monkeypatch.setattr("openpilot.common.params.Params", FakeParams)
  assert rotation.read_rotation() == {}
  assert rotation.load_rotation() == rotation.POP_ROTATION

  # A completed Phase 1 fit is deliberately invalid under the new optical ABI.
  FakeParams.value = {"fitted": True, "rotvec": [0.1, 0.2, 0.3]}
  assert rotation.read_rotation() == {}
  assert rotation.load_rotation() == rotation.POP_ROTATION

  FakeParams.value = {
    "fitted": True,
    "geometryVersion": rotation.GEOMETRY_VERSION,
    "rotvec": [0.1, 0.2, 0.3],
  }
  assert rotation.load_rotation() == (0.1, 0.2, 0.3)


def test_completed_rotation_survives_reboot_but_partial_rotation_does_not():
  from openpilot.common.params import Params

  fit = Fit((0.01, 0.02, 0.03))
  fit.fits = [(0.04, 0.05, 0.06)] * N_FRAMES
  fit.mean = (0.04, 0.05, 0.06)
  save_completed_rotation((0.04, 0.05, 0.06), fit)

  # Exercise the real synchronous Params API and its on-disk JSON encoding.
  params = Params()
  stored = params.get(rotation.ROTATION_PARAM)
  assert Path(params.get_param_path(rotation.ROTATION_PARAM)).is_file()
  assert stored == {
    "rotvec": [0.04, 0.05, 0.06],
    "geometryVersion": rotation.GEOMETRY_VERSION,
    "fitted": True,
    "n": N_FRAMES,
    "spread_deg": 0.0,
    "applied": [0.01, 0.02, 0.03],
  }

  # read_rotation() creates a fresh Params instance, modeling the next boot.
  assert rotation.read_rotation() == stored
  assert rotation.load_rotation() == (0.04, 0.05, 0.06)

  params.put(rotation.ROTATION_PARAM, {
    "fitted": False,
    "geometryVersion": rotation.GEOMETRY_VERSION,
    "rotvec": [0.7, 0.8, 0.9],
  })
  assert rotation.read_rotation() == {}
  assert rotation.load_rotation() == rotation.POP_ROTATION


def test_reproject_session_is_latched_across_chestnut_disconnect(monkeypatch):
  from openpilot.selfdrive.modeld import reproject_config

  class MemoryParams:
    def __init__(self):
      self.values = {}

    def get_bool(self, key):
      return bool(self.values.get(key, False))

    def put_bool(self, key, value):
      self.values[key] = value

  params = MemoryParams()
  monkeypatch.setattr(reproject_config, "TICI", True)
  monkeypatch.setattr(reproject_config, "get_model_profile", lambda *_args: ("cinque-v3", "", ""))
  monkeypatch.setattr(reproject_config, "chestnut_firmware_ready", lambda: True)
  # Manager can run its predicate before modeld starts. Its first evaluation
  # must both select the session and make reprojectd eligible to start.
  assert reproject_process(True, params, None, None)
  assert params.values[REPROJECT_SESSION_PARAM]

  # Neither manager's process predicate nor a restarted modeld re-probes the
  # transient USB state once the onroad session has selected virtual C4.
  monkeypatch.setattr(reproject_config, "chestnut_firmware_ready", lambda: False)
  assert reproject_expected(params)
  assert select_reproject_session(params)
  assert reproject_process(True, params, None, None)
  assert not reproject_process(False, params, None, None)


def test_no_chestnut_means_no_reproject_session(monkeypatch):
  from openpilot.selfdrive.modeld import reproject_config

  class MemoryParams:
    values = {}

    def get_bool(self, key):
      return bool(self.values.get(key, False))

    def put_bool(self, key, value):
      self.values[key] = value

  params = MemoryParams()
  monkeypatch.setattr(reproject_config, "TICI", True)
  monkeypatch.setattr(reproject_config, "get_model_profile", lambda *_args: ("cinque-v3", "", ""))
  assert not select_reproject_session(params, chestnut_ready=False)
  assert not reproject_expected(params)


def test_qcom_priority_is_only_overridden_by_reprojectd():
  modeld_source_path = Path(modeld.__file__)
  modeld_source = modeld_source_path.read_text()
  reprojectd_source = modeld_source_path.with_name("reprojectd.py").read_text()

  assert "QCOM_PRIORITY" not in modeld_source
  assert "os.environ['GMMU'] = '0'" in modeld_source
  assert "os.environ['DEV'] = 'QCOM' if TICI else 'LLVM'" in modeld_source

  priority_override = 'os.environ["QCOM_PRIORITY"] = "1"'
  assert priority_override in reprojectd_source
  assert reprojectd_source.index(priority_override) < reprojectd_source.index("from tinygrad")


def test_model_lab_keeps_native_c3x_camera_with_big_profile_configured(monkeypatch):
  from openpilot.selfdrive.modeld import reproject_config

  class MemoryParams:
    def __init__(self):
      self.values = {"ModelLabConfig": {"enabled": True, "lateralModel": "lat", "longitudinalModel": "long"}}

    def get(self, key):
      return self.values.get(key)

    def get_bool(self, key):
      return bool(self.values.get(key, False))

    def put_bool(self, key, value):
      self.values[key] = value

  params = MemoryParams()
  monkeypatch.setattr(reproject_config, "TICI", True)
  monkeypatch.setattr(reproject_config, "get_model_profile", lambda *_args: ("cinque-v3", "", ""))
  assert not select_reproject_session(params, chestnut_ready=True)
  assert not params.get_bool(REPROJECT_SESSION_PARAM)

  # Model Laboratory's existing loader contract uses the dimensions of the
  # selected camerad stream, which is native C3X on this device.
  camera_path = modeld.CameraPath("camerad", (1928, 1208))
  assert camera_path.warp_geometry("tizi", "ar0231") == ("tizi", "ar0231")


def _load_bundled_small_model_for_inspection(monkeypatch):
  """Load the checked-in artifact without executing its compiled kernels.

  The bundled pickle contains legacy tinygrad Ops/UOp enum encodings. These
  temporary unpickle shims let this host inspect its camera-keyed artifact map;
  QCOM allocations are redirected to CPU. No model inference is run.
  """
  from tinygrad.device import Device
  from tinygrad.uop.ops import Ops, UOpMetaClass

  original_device_class = Device.get_class
  monkeypatch.setattr(
    Device,
    "get_class",
    lambda ix: original_device_class("CPU") if ix.startswith("QCOM") else original_device_class(ix),
  )

  def legacy_ops_missing(cls, value):
    member = int.__new__(cls, value)
    member._name_, member._value_ = f"LEGACY_{value}", value
    return member

  monkeypatch.setattr(Ops, "_missing_", classmethod(legacy_ops_missing))
  original_uop_call = UOpMetaClass.__call__
  monkeypatch.setattr(
    UOpMetaClass,
    "__call__",
    lambda cls, *args, **kwargs: original_uop_call(cls, *args[:5], **kwargs),
  )

  artifact_path = modeld.Path(__file__).parents[1] / "models" / "driving_tinygrad.pkl"
  return modeld._load_model_artifact(artifact_path)


def test_bundled_small_model_artifact_has_virtual_c4_warp(monkeypatch):
  artifact = _load_bundled_small_model_for_inspection(monkeypatch)

  assert (1344, 760) in artifact
  assert (1928, 1208) in artifact
  modeld._require_artifact_camera_resolution(artifact, 1344, 760)


def test_upstream_precompiled_warp_requires_c4_frame_body_and_transform_abi():
  specs = {
    "input_frame": ((2, 1_622_016), None, "CPU"),
    "M_inv": ((2, 3, 3), None, "CPU"),
  }
  modeld._require_precompiled_warp_abi(specs, 1344, 760)

  specs["input_frame"] = ((2, 1_622_144), None, "CPU")
  with pytest.raises(ValueError, match="frame shape"):
    modeld._require_precompiled_warp_abi(specs, 1344, 760)


def test_dark_seam_fallback_holds_per_unit_terms():
  meter = SeamMeter.__new__(SeamMeter)
  meter.state = np.array([1.0, 3.0, -4.0, 0.1, -0.2, 0.9, 1.0, 1.1, 1.2], dtype=np.float32)
  meter.n_calls, meter.every, meter.moving = 1, 2, False
  meter.alpha = 0.3
  meter.measure = lambda _wide, _narrow: None

  state = meter.update(np.zeros(1), np.zeros(1), model_gain=1.5)

  np.testing.assert_allclose(state[1:5], [3.0, -4.0, 0.1, -0.2])
  assert state[0] == 1.5
  assert np.all(np.abs(state[5:] - 1.5) < np.abs(np.array([0.9, 1.0, 1.1, 1.2]) - 1.5))


def test_phase2_geometry_matches_amy_population_optics():
  from openpilot.selfdrive.modeld.reproject_c4 import geometry, tables

  assert geometry.X3_WIDE_POP == {
    "f": 597.732, "cx": 963.936, "cy": 603.959,
    "k": (-0.011968, 0.024043, -0.0091132), "tc": 1.51354,
  }
  assert geometry.POP_ROTATION == (0.0154781, -0.0225994, -0.00068013)
  assert geometry.FEATHER_PX == 50
  assert tables.TABLE_VERSION == 8


def test_fixed_twelve_frame_median_fit(monkeypatch):
  fit = Fit((0.0, 0.0, 0.0))
  values = [(0.0, 0.0, 0.0)] * (N_FRAMES - 1) + [(0.1, -0.1, 0.01)]
  results = iter((value, 15, 0.1) for value in values)
  monkeypatch.setattr("openpilot.selfdrive.modeld.reprojectcalibd.RC.fit_rotation", lambda *_args, **_kwargs: next(results))

  for frame_id in range(N_FRAMES - 1):
    assert fit.frame(None, None, frame_id) is not None
  assert not fit.complete

  assert fit.frame(None, None, N_FRAMES - 1) is not None
  assert fit.complete
  assert fit.mean == (0.0, 0.0, 0.0)


def test_reproject_ui_phase_hold_is_wired():
  source = (Path(modeld.__file__).parents[1] / "ui/onroad/augmented_road_view.py").read_text()
  ui_state_source = (Path(modeld.__file__).parents[1] / "ui/ui_state.py").read_text()

  assert "UI_PHASE_TARGET_NS = 22_000_000" in source
  assert "UI_PHASE_TOLERANCE_NS = 2_000_000" in source
  assert "FRAME_PERIOD_NS = 50_000_000" in source
  assert 'sm.alive["reprojectState"]' in source
  assert "def _restore_fps(self)" in source
  assert "def hide_event(self)" in source
  assert "CLOCK_BOOTTIME" in source
  assert '"reprojectState"' in ui_state_source
