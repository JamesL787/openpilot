"""comma 3X -> virtual comma 4 reprojection (ported from vfn), on StarPilot 7.0.

vfn's tests of its own modeld internals (Model Laboratory, its precompiled-warp ABI, legacy tinygrad ops, the UI phase
hold) are not ported; the session tests are rewritten for 7.0's model catalog, and a CPU smoke test runs the kernel
on 7.0's tinygrad pin.
"""
from pathlib import Path

import numpy as np

from openpilot.selfdrive.modeld import reproject_config
from openpilot.selfdrive.modeld.reproject_c4 import cameras, rotation
from openpilot.selfdrive.modeld.reproject_c4.meter import SeamMeter
from openpilot.selfdrive.modeld.reprojectcalibd import Fit, N_FRAMES, save_completed_rotation
from openpilot.selfdrive.modeld.reproject_config import REPROJECT_SESSION_PARAM, reproject_expected, select_reproject_session
from openpilot.system.manager.process_config import reproject as reproject_process


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
  FakeParams.value = {"fitted": True, "rotvec": [0.1, 0.2, 0.3]}  # ty: ignore[invalid-assignment]
  assert rotation.read_rotation() == {}
  assert rotation.load_rotation() == rotation.POP_ROTATION

  FakeParams.value = {  # ty: ignore[invalid-assignment]
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
  }, block=True)
  assert rotation.read_rotation() == {}
  assert rotation.load_rotation() == rotation.POP_ROTATION


def test_dark_seam_fallback_holds_per_unit_terms():
  meter = SeamMeter.__new__(SeamMeter)
  meter.state = np.array([1.0, 3.0, -4.0, 0.1, -0.2, 0.9, 1.0, 1.1, 1.2], dtype=np.float32)
  meter.n_calls, meter.every, meter.moving = 1, 2, False
  meter.alpha = 0.3
  meter.measure = lambda _wide, _narrow: None  # ty: ignore[invalid-assignment]

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


class MemoryParams:
  def __init__(self):
    self.values = {}

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def put_bool(self, key, value, block=False):
    self.values[key] = value


def _a_3x_with_a_big_model(monkeypatch, *, chestnut=True, big=True):
  monkeypatch.setattr(reproject_config, "_device_supported", lambda: True)
  monkeypatch.setattr(reproject_config, "_big_model_selected", lambda ready: bool(ready and big))
  monkeypatch.setattr("openpilot.selfdrive.modeld.helpers.chestnut_present", lambda: chestnut)


def test_reproject_session_is_latched_across_chestnut_disconnect(monkeypatch):
  params = MemoryParams()
  _a_3x_with_a_big_model(monkeypatch)
  # manager may evaluate its predicate before modeld starts; the first evaluation selects and latches the session
  assert reproject_process(True, params, None)  # ty: ignore[invalid-argument-type]
  assert params.values[REPROJECT_SESSION_PARAM]
  # once latched, neither the predicate nor a restarted modeld re-probes a Chestnut that dropped for a moment
  _a_3x_with_a_big_model(monkeypatch, chestnut=False)
  assert reproject_expected(params)  # ty: ignore[invalid-argument-type]
  assert select_reproject_session(params)  # ty: ignore[invalid-argument-type]
  assert reproject_process(True, params, None)  # ty: ignore[invalid-argument-type]
  assert not reproject_process(False, params, None)  # ty: ignore[invalid-argument-type]


def test_no_chestnut_or_no_big_model_means_no_reproject_session(monkeypatch):
  params = MemoryParams()
  _a_3x_with_a_big_model(monkeypatch)
  assert not select_reproject_session(params, chestnut_ready=False)  # ty: ignore[invalid-argument-type]
  _a_3x_with_a_big_model(monkeypatch, big=False)
  assert not select_reproject_session(params, chestnut_ready=True)  # ty: ignore[invalid-argument-type]
  assert not reproject_expected(params)  # ty: ignore[invalid-argument-type]


def test_only_a_3x_gets_the_virtual_comma_4_path(monkeypatch):
  params = MemoryParams()
  monkeypatch.setattr(reproject_config, "_device_supported", lambda: False)
  monkeypatch.setattr(reproject_config, "_big_model_selected", lambda ready: True)
  assert not select_reproject_session(params, chestnut_ready=True)  # ty: ignore[invalid-argument-type]
  params.values[REPROJECT_SESSION_PARAM] = True
  assert not reproject_expected(params)  # ty: ignore[invalid-argument-type]


def test_qcom_priority_is_only_raised_by_reprojectd():
  modeld_source = Path(reproject_config.__file__).with_name("modeld.py").read_text()
  reprojectd_source = Path(reproject_config.__file__).with_name("reprojectd.py").read_text()
  assert "QCOM_PRIORITY" not in modeld_source
  override = 'os.environ["QCOM_PRIORITY"] = "1"'
  assert reprojectd_source.index(override) < reprojectd_source.index("from tinygrad")


def test_kernel_runs_on_7_0_tinygrad(tmp_path):
  # Build the real 3X -> comma 4 tables and run the gather/composite kernel on CPU against a known source.
  from tinygrad import Tensor
  from openpilot.selfdrive.modeld import reproject_c4 as RC
  from openpilot.selfdrive.modeld.reproject_c4.kernel import Reprojector
  from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
  src_wh = (1928, 1208)
  tables = RC.load_tables(src_wh, RC.C4_CAM, str(tmp_path), RC.calib_from_rotvec(RC.POP_ROTATION))
  rp = Reprojector(tables, RC.C4_CAM, "CPU")
  src_size = get_nv12_info(*src_wh)[3]
  rng = np.random.default_rng(0)
  wide = rng.integers(0, 256, src_size, dtype=np.uint8)
  narrow = rng.integers(0, 256, src_size, dtype=np.uint8)
  out_w, out_n = rp(Tensor(wide, device="CPU"), Tensor(narrow, device="CPU"))
  out_w, out_n = out_w.numpy(), out_n.numpy()
  assert out_w.shape == out_n.shape == (rp.body,)
  pw = tables["wide"]["pw"]
  valid = pw < RC.INVALID_BIT
  assert valid.mean() > 0.85   # most of the comma 4 wide view lies inside the 3X wide lens (0.899 on the fleet lens)
  np.testing.assert_array_equal(out_w[valid], wide[pw[valid] & RC.IDX_BITS])
  again = RC.load_tables(src_wh, RC.C4_CAM, str(tmp_path), RC.calib_from_rotvec(RC.POP_ROTATION))   # cached
  np.testing.assert_array_equal(again["wide"]["pw"], pw)
