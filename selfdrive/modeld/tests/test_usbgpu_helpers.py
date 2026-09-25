import base64
import io
import pickle
import struct
from types import MethodType
from types import SimpleNamespace

import numpy as np
import pytest

from openpilot.selfdrive.modeld import modeld
from openpilot.selfdrive.modeld.compile_modeld import validate_serialized_artifact
from openpilot.selfdrive.modeld.helpers import dump_oob, load_oob, tinygrad_dev_config
from scripts import model_compiler


class _FakePrecompiledWarp:
  def __init__(self, output_shape):
    self.output_shape = output_shape
    self.inputs = None

  def __call__(self, **inputs):
    self.inputs = inputs
    return modeld.Tensor.zeros(self.output_shape, dtype="uint8", device="CPU").realize()


class _FakePrecompiledPolicy:
  def __init__(self):
    self.inputs = None

  def __call__(self, output_buffers, **inputs):
    self.inputs = inputs
    output_buffers["outputs"].assign(0).realize()


class _FakeParser:
  def parse_outputs(self, outputs):
    return outputs


class _LegacyBufferReduce:
  """Mirror the pre-BufferStorage pickle tuple emitted by VFN's old tinygrad."""
  def __reduce__(self):
    from tinygrad.device import Buffer
    from tinygrad.dtype import dtypes

    # The seventh positional item used to be uop_refcount; it now maps to base.
    return Buffer, ("CPU", 4, dtypes.uint8, None, None, None, 0)


def test_external_gpu_keeps_the_native_device_available():
  assert tinygrad_dev_config(True, tici=True) == "QCOM;USB+AMD:LLVM"
  assert tinygrad_dev_config(False, tici=True) == "QCOM"
  assert tinygrad_dev_config(True, tici=False) == "CPU:LLVM;USB+AMD:LLVM"


def test_current_tinygrad_loads_legacy_vfn_buffer_pickle():
  buffer = pickle.loads(pickle.dumps(_LegacyBufferReduce(), protocol=5))

  assert buffer.device == "CPU"
  assert buffer.size == 4
  assert buffer._base is None


def test_tinygrad_call_info_accepts_old_and_new_pickle_schemas():
  from tinygrad.dtype import dtypes
  from tinygrad.uop.ops import CallInfo

  assert CallInfo(None, "legacy", False, False, None).dtype is dtypes.void
  assert CallInfo(None, "current", False, False, None, dtypes.float).dtype is dtypes.float


def test_external_gpu_selects_amd_without_probing_other_backends(monkeypatch, tmp_path):
  from openpilot.selfdrive.modeld import helpers

  monkeypatch.setattr(helpers, "TG_INPUT_DEVICES_PATH", tmp_path / "missing.json")
  monkeypatch.setattr(helpers, "_default_tinygrad_backend", lambda: "QCOM")
  monkeypatch.setattr(
    helpers.Device,
    "get_available_devices",
    lambda: (_ for _ in ()).throw(AssertionError("must not probe every tinygrad backend")),
  )

  assert helpers.get_tg_input_devices("selfdrive.modeld.modeld", usbgpu=True) == {
    "WARP_DEV": "QCOM",
    "QUEUE_DEV": "AMD",
  }


def test_external_gpu_uses_a_longer_load_watchdog():
  assert modeld.BIG_MODEL_LOAD_WAIT_TIMEOUT_MS == 60000
  assert modeld.BIG_MODEL_RUN_WAIT_TIMEOUT_MS == 3000


def test_serialized_artifact_validation_rejects_trailing_data(tmp_path):
  artifact = tmp_path / "artifact.pkl"
  artifact.write_bytes(pickle.dumps({"ok": True}) + b"trailing")

  with pytest.raises(ValueError, match="trailing data"):
    validate_serialized_artifact(artifact, out_of_band=False)


def test_serialized_artifact_validation_rejects_incomplete_oob_data(tmp_path):
  artifact = tmp_path / "artifact.pkl"
  with artifact.open("wb") as output:
    dump_oob({"ok": True}, output)
  artifact.write_bytes(artifact.read_bytes()[:-1])

  with pytest.raises((EOFError, pickle.UnpicklingError)):
    validate_serialized_artifact(artifact, out_of_band=True)


def test_external_gpu_voltage_uses_hardware_specific_source():
  panda_type = modeld.log.PandaState.PandaType
  panda_states = [SimpleNamespace(pandaType=panda_type.dos, voltage=230)]
  peripheral_state = SimpleNamespace(pandaType=panda_type.dos, voltage=13550)

  assert modeld._external_gpu_power_voltage("tici", panda_states, peripheral_state) == 13550

  panda_states = [SimpleNamespace(pandaType=panda_type.tres, voltage=14100)]
  peripheral_state = SimpleNamespace(pandaType=panda_type.tres, voltage=12800)
  assert modeld._external_gpu_power_voltage("tizi", panda_states, peripheral_state) == 14100

  panda_states = [SimpleNamespace(pandaType=panda_type.cuatro, voltage=13200)]
  peripheral_state = SimpleNamespace(pandaType=panda_type.cuatro, voltage=12800)
  assert modeld._external_gpu_power_voltage("mici", panda_states, peripheral_state) == 13200


def test_external_gpu_power_must_remain_stable():
  ready, stable_since = modeld._external_gpu_power_ready(9900, 10.0, None)
  assert not ready
  assert stable_since is None

  ready, stable_since = modeld._external_gpu_power_ready(14100, 11.0, stable_since)
  assert not ready
  assert stable_since == 11.0

  ready, stable_since = modeld._external_gpu_power_ready(14100, 13.9, stable_since)
  assert not ready
  ready, stable_since = modeld._external_gpu_power_ready(14100, 14.0, stable_since)
  assert ready

  ready, stable_since = modeld._external_gpu_power_ready(11900, 15.0, stable_since)
  assert ready
  assert stable_since == 11.0


def test_egmp_ready_uses_accelerator_ready_bit():
  bus = 1
  not_ready = SimpleNamespace(address=0x35, src=bus, dat=bytes([0, 0, 0, 0x00]))
  wrong_bus = SimpleNamespace(address=0x35, src=0, dat=bytes([0, 0, 0, 0x40]))
  ready = SimpleNamespace(address=0x35, src=bus, dat=bytes([0, 0, 0, 0x40]))

  assert not modeld._egmp_vehicle_ready([not_ready, wrong_bus], bus)
  assert modeld._egmp_vehicle_ready([not_ready, ready], bus)


def test_current_amd_runtime_uses_hcq2_by_default():
  from tinygrad.helpers import HCQ2

  # The upstream precompiled artifacts are built for the HCQ2 AMD runtime.
  # HCQ1's AMDSignal polling implementation is intentionally not part of the
  # current compatibility contract.
  assert HCQ2.value == 1


def test_external_gpu_wait_timeout_updates_tinygrad_cache(monkeypatch):
  from tinygrad.helpers import getenv

  try:
    monkeypatch.setenv("HCQDEV_WAIT_TIMEOUT_MS", "30000")
    getenv.cache_clear()
    assert getenv("HCQDEV_WAIT_TIMEOUT_MS", 0) == 30000

    modeld._set_hcq_wait_timeout(3000)
    assert getenv("HCQDEV_WAIT_TIMEOUT_MS", 0) == 3000
  finally:
    getenv.cache_clear()


def test_chestnut_telemetry_is_bounded_when_amd_is_unavailable(monkeypatch):
  from cereal.services import SERVICE_LIST

  class FakePubMaster:
    def __init__(self):
      self.sent = []

    def send(self, service, message):
      self.sent.append((service, message))

  publisher = FakePubMaster()
  monkeypatch.setattr(modeld, "Device", SimpleNamespace(_opened_devices=set()))

  telemetry = modeld.ChestnutState(publisher, big=True)
  telemetry.send()

  assert SERVICE_LIST["chestnutState"].frequency == 10.0
  assert len(publisher.sent) == 1
  service, message = publisher.sent[0]
  assert service == "chestnutState"
  assert message.which() == "chestnutState"
  assert not message.valid


def test_chestnut_power_telemetry_works_before_amd_initializes(monkeypatch):
  class FakePubMaster:
    def __init__(self):
      self.sent = []

    def send(self, service, message):
      self.sent.append((service, message))

  class FakeHandle:
    def controlRead(self, *_args, **_kwargs):
      return struct.pack("<Hh?", 12100, 850, True)

    def close(self):
      pass

  class FakeContext:
    def openByVendorIDAndProductID(self, *_args, **_kwargs):
      return FakeHandle()

    def close(self):
      pass

  publisher = FakePubMaster()
  monkeypatch.setattr(modeld, "Device", SimpleNamespace(_opened_devices=set()))
  monkeypatch.setattr(modeld.usb1, "USBContext", FakeContext)

  telemetry = modeld.ChestnutState(publisher, big=False)
  telemetry.send()

  _, message = publisher.sent[0]
  assert message.valid
  assert message.chestnutState.supplyVoltage == 12100
  assert message.chestnutState.supplyCurrent == 850
  assert message.chestnutState.supplyFault


def test_tinygrad_disk_cache_connection_is_closed_between_models(monkeypatch):
  import tinygrad.helpers as tinygrad_helpers

  class FakeConnection:
    def __init__(self):
      self.closed = False

    def close(self):
      self.closed = True

  connection = FakeConnection()
  monkeypatch.setattr(tinygrad_helpers, "_db_connection", connection)

  modeld._close_tinygrad_disk_cache_connection()

  assert connection.closed
  assert tinygrad_helpers._db_connection is None


def test_tinygrad_thread_local_cache_holder_survives_cleanup(monkeypatch):
  import threading
  import tinygrad.helpers as tinygrad_helpers

  class FakeConnection:
    def __init__(self):
      self.closed = False

    def close(self):
      self.closed = True

  holder = threading.local()
  connection = FakeConnection()
  holder.conn = connection
  monkeypatch.setattr(tinygrad_helpers, "_db_connection", holder)

  modeld._close_tinygrad_disk_cache_connection()

  assert connection.closed
  assert tinygrad_helpers._db_connection is holder
  assert not hasattr(holder, "conn")


def test_tinygrad_empty_thread_local_cache_holder_is_safe(monkeypatch):
  import threading
  import tinygrad.helpers as tinygrad_helpers

  holder = threading.local()
  monkeypatch.setattr(tinygrad_helpers, "_db_connection", holder)

  modeld._close_tinygrad_disk_cache_connection()

  assert tinygrad_helpers._db_connection is holder


def test_external_gpu_load_finishes_before_native_model_can_start(monkeypatch):
  calls = []

  class FakeModelState:
    uses_external_gpu = True

    def __init__(self, cam_w, cam_h, external_gpu_active, model_id_override, write_model_version,
                 model_version_override=None, **_kwargs):
      calls.append(("model", cam_w, cam_h, external_gpu_active, model_id_override, write_model_version))

    def warmup(self):
      calls.append("warmup")

  monkeypatch.setattr(modeld, "wait_usbgpu_link", lambda: calls.append("link"))
  monkeypatch.setattr(modeld, "wait_for_external_gpu_power_ready", lambda CP: calls.append(("power", CP)))
  monkeypatch.setattr(modeld, "_set_hcq_wait_timeout", lambda timeout: calls.append(("timeout", timeout)))
  monkeypatch.setattr(modeld, "_close_tinygrad_disk_cache_connection", lambda: calls.append("close_cache"))
  monkeypatch.setattr(modeld, "ModelState", FakeModelState)
  monkeypatch.setattr(
    modeld,
    "tinygrad_dev_config",
    lambda *_args: (_ for _ in ()).throw(AssertionError("runtime must not change tinygrad's process-global DEV")),
  )

  loaded = modeld._load_external_gpu_model(1928, 1208, "big-model", CP="car-params")

  assert isinstance(loaded, FakeModelState)
  assert calls == [
    ("power", "car-params"),
    ("timeout", modeld.BIG_MODEL_LOAD_WAIT_TIMEOUT_MS),
    "link",
    ("model", 1928, 1208, True, "big-model", False),
    "warmup",
    "close_cache",
    ("timeout", modeld.BIG_MODEL_RUN_WAIT_TIMEOUT_MS),
  ]


def test_external_gpu_nonfinite_outputs_trigger_fallback(monkeypatch):
  call_order = []

  class FakeTensor:
    @staticmethod
    def from_blob(*_args, **_kwargs):
      return FakeTensor()

  class FakeOutput:
    def numpy(self):
      call_order.append("output_sync")
      return np.array([np.nan], dtype=np.float32)

  state = modeld.ModelState.__new__(modeld.ModelState)
  state.uses_external_gpu = True
  state.fused = False
  state.frame_buf_size = 4
  state.vision_input_names = ["img", "big_img"]
  state.road_key = "img"
  state.wide_key = "big_img"
  state._blob_cache = {}
  state._warp_dev = "CPU"
  state._queue_dev = "CPU"
  state.desire_key = "desire_pulse"
  state.prev_desired_curv_key = None
  state.numpy_inputs = {"desire_pulse": np.zeros(8, dtype=np.float32)}
  state.npy = {
    "desire": np.zeros(8, dtype=np.float32),
    "tfm": np.zeros((3, 3), dtype=np.float32),
    "big_tfm": np.zeros((3, 3), dtype=np.float32),
  }
  state.prev_desire = np.zeros(8, dtype=np.float32)
  state.prev_blinker_on = False
  state.warp_input_keys = ()
  state.policy_input_keys = ()
  state.input_queues = {}
  state.image_history_pipeline = modeld.IMAGE_HISTORY_IN_POLICY
  state.warp_enqueue = lambda **_kwargs: object()
  state.run_policy = lambda **_kwargs: (FakeOutput(),)
  monkeypatch.setattr(modeld, "Tensor", FakeTensor)
  buffers = {
    "img": SimpleNamespace(data=bytearray(4)),
    "big_img": SimpleNamespace(data=bytearray(4)),
  }
  transforms = {
    "img": np.eye(3, dtype=np.float32),
    "big_img": np.eye(3, dtype=np.float32),
  }
  inputs = {"desire_pulse": np.zeros(8, dtype=np.float32)}

  callbacks = []

  def send_telemetry():
    call_order.append("telemetry")
    callbacks.append("sent")

  with pytest.raises(RuntimeError, match="external GPU model output not finite"):
    state.run(buffers, transforms, inputs, False, after_output_sync=send_telemetry)
  assert call_order == ["output_sync", "telemetry"]
  assert callbacks == ["sent"]


def test_external_gpu_implausible_finite_outputs_trigger_fallback():
  with pytest.raises(RuntimeError, match="output magnitude implausible"):
    modeld._validate_external_gpu_outputs([
      np.array([0.0, modeld.MAX_ABS_EXTERNAL_MODEL_OUTPUT * 2], dtype=np.float32),
    ])


def test_external_gpu_reasonable_finite_outputs_are_accepted():
  modeld._validate_external_gpu_outputs([
    np.array([-100.0, 0.0, 100.0], dtype=np.float32),
  ])


def test_fused_model_copies_live_frames_and_runs_single_graph():
  calls = []

  class FakeOutput:
    @staticmethod
    def numpy():
      return np.zeros(2, dtype=np.float32)

  state = modeld.ModelState.__new__(modeld.ModelState)
  state.fused = True
  state.fused_legacy = True
  state.frame_copy_size = 4
  state.frame_views = {
    "img": np.zeros(4, dtype=np.uint8),
    "big_img": np.zeros(4, dtype=np.uint8),
  }
  state.desire_key = "desire"
  state.prev_desired_curv_key = None
  state.numpy_inputs = {"desire": np.zeros((1, modeld.ModelConstants.DESIRE_LEN), dtype=np.float32)}
  state.npy = {
    "desire": np.zeros(modeld.ModelConstants.DESIRE_LEN, dtype=np.float32),
    "tfm": np.zeros((3, 3), dtype=np.float32),
    "big_tfm": np.zeros((3, 3), dtype=np.float32),
  }
  state.prev_desire = np.zeros(modeld.ModelConstants.DESIRE_LEN, dtype=np.float32)
  state.prev_blinker_on = False
  state.road_key = "img"
  state.wide_key = "big_img"
  state.input_queues = {"packed": "host-buffer"}
  state.model_input_keys = ("packed",)
  state.run_model = lambda **kwargs: calls.append(kwargs) or [FakeOutput()]
  state.uses_external_gpu = False
  state.model_type = "supercombo"
  state.parser = SimpleNamespace(parse_outputs=lambda _outputs: {"plan": np.zeros(1, dtype=np.float32)})
  state.output_slices = {"plan": slice(0, 1)}
  state.last_warp_output = object()

  output = state.run(
    {
      "img": SimpleNamespace(data=bytearray([1, 2, 3, 4, 99])),
      "big_img": SimpleNamespace(data=bytearray([5, 6, 7, 8, 99])),
    },
    {"img": np.eye(3, dtype=np.float32), "big_img": np.eye(3, dtype=np.float32)},
    {"desire": np.zeros(modeld.ModelConstants.DESIRE_LEN, dtype=np.float32)},
    False,
  )

  np.testing.assert_array_equal(state.frame_views["img"], [1, 2, 3, 4])
  np.testing.assert_array_equal(state.frame_views["big_img"], [5, 6, 7, 8])
  assert calls == [{"packed": "host-buffer"}]
  assert state.last_warp_output is None
  assert output is not None


def test_out_of_band_artifact_round_trip():
  artifact = {"weights": np.arange(32, dtype=np.float32), "metadata": {"version": 1}}
  stream = io.BytesIO()
  dump_oob(artifact, stream)
  stream.seek(0)

  restored = load_oob(stream)
  assert restored["metadata"] == artifact["metadata"]
  np.testing.assert_array_equal(restored["weights"], artifact["weights"])


def test_fused_artifact_requires_matching_tinygrad():
  artifact = {
    "format_version": modeld.ARTIFACT_FORMAT_VERSION,
    "execution_mode": "fused",
    "run_model": {},
    "compiler": {"tinygrad_commit": "wrong"},
  }
  with pytest.raises(ValueError, match="tinygrad mismatch"):
    modeld._normalize_model_artifact(artifact)


def test_fused_artifact_accepts_matching_tinygrad():
  artifact = {
    "format_version": modeld.ARTIFACT_FORMAT_VERSION,
    "execution_mode": "fused",
    "run_model": {},
    "compiler": {"tinygrad_commit": modeld.tinygrad_commit()},
  }
  assert modeld._normalize_model_artifact(artifact) is artifact


def test_upstream_precompiled_artifact_is_normalized():
  output_slices = {"plan": slice(0, 10)}
  artifact = {
    "run": lambda **_kwargs: None,
    "input_specs": {"new_img": ((2, 6, 128, 256), "uint8", "AMD")},
    "output_specs": {"outputs": ((1, 10), "float32", "AMD")},
    "metadata": {
      "input_shapes": {"new_img": (2, 6, 128, 256)},
      "metadata": {"output_slices": base64.b64encode(pickle.dumps(output_slices)).decode()},
    },
  }

  normalized = modeld._normalize_model_artifact(artifact)

  assert normalized["execution_mode"] == modeld.UPSTREAM_PRECOMPILED_EXECUTION_MODE
  assert normalized["image_history_pipeline"] == modeld.IMAGE_HISTORY_IN_POLICY
  assert normalized["output_slices"] == output_slices


def test_upstream_precompiled_artifact_requires_output_slices():
  artifact = {
    "run": lambda **_kwargs: None,
    "input_specs": {"new_img": ((2, 6, 128, 256), "uint8", "AMD")},
    "output_specs": {"outputs": ((1, 10), "float32", "AMD")},
    "metadata": {"input_shapes": {"new_img": (2, 6, 128, 256)}, "metadata": {}},
  }

  with pytest.raises(ValueError, match="output_slices"):
    modeld._normalize_model_artifact(artifact)


def test_upstream_precompiled_warp_path_is_camera_specific():
  assert modeld._upstream_precompiled_warp_path(1928, 1208, True).name == "big_driving_warp_1928x1208_tinygrad.pkl"
  assert modeld._upstream_precompiled_warp_path(1344, 760, True).name == "big_driving_warp_1344x760_tinygrad.pkl"
  assert modeld._upstream_precompiled_warp_path(1928, 1208, False).name == "small_driving_warp_1928x1208_tinygrad.pkl"
  assert modeld._upstream_precompiled_warp_path(1344, 760, False).name == "small_driving_warp_1344x760_tinygrad.pkl"


def test_upstream_precompiled_runtime_packs_frames_with_warp_inputs(tmp_path, monkeypatch):
  cam_w, cam_h = 8, 8
  stride, y_height, uv_height, full_frame_size = modeld.get_nv12_info(cam_w, cam_h)
  frame_size = modeld.nv12_copy_size(stride, y_height, uv_height)
  assert frame_size < full_frame_size
  warp_path = tmp_path / "big_driving_warp_8x8_tinygrad.pkl"
  warp_path.touch()
  fake_warp = _FakePrecompiledWarp((2, 6, 2, 2))
  monkeypatch.setattr(modeld, "_upstream_precompiled_warp_path", lambda *_: warp_path)
  monkeypatch.setattr(modeld.pickle, "load", lambda _: {
    "run": fake_warp,
    "input_specs": {
      "input_frame": ((2, frame_size), "uint8", "CPU"),
      "M_inv": ((2, 3, 3), "float32", "CPU"),
    },
  })
  policy = _FakePrecompiledPolicy()
  input_shapes = {
    "new_img": (2, 6, 2, 2),
    "desire": (1, modeld.ModelConstants.DESIRE_LEN),
    "traffic_convention": (1, 2),
    "action_t": (1, 2),
  }
  artifact = {
    "run": policy,
    "input_specs": {
      name: (shape, "uint8" if name == "new_img" else "float32", "CPU")
      for name, shape in input_shapes.items()
    },
    "output_specs": {"outputs": ((1, 1), "float32", "CPU")},
    "metadata": {"input_shapes": input_shapes},
    "output_slices": {"stub": slice(0, 1)},
  }
  state = modeld.ModelState.__new__(modeld.ModelState)
  state.uses_external_gpu = False
  state._queue_dev = "CPU"
  state._warp_dev = "CPU"
  state.reprojector = None
  state._reproject_blob_cache = {}
  state._init_upstream_precompiled(artifact, cam_w, cam_h)
  state.parser = _FakeParser()

  road = np.arange(frame_size, dtype=np.uint8)
  wide = np.arange(frame_size, dtype=np.uint8) + 1
  eye = np.eye(3, dtype=np.float32)
  result = state._run_upstream_precompiled(
    {"img": SimpleNamespace(data=road), "big_img": SimpleNamespace(data=wide)},
    {"img": eye, "big_img": eye * 2},
    {
      "desire": np.zeros(modeld.ModelConstants.DESIRE_LEN, dtype=np.float32),
      "traffic_convention": np.array([1, 0], dtype=np.float32),
      "action_t": np.array([.1, .2], dtype=np.float32),
    },
    None,
    None,
    False,
  )

  np.testing.assert_array_equal(fake_warp.inputs["input_frame"].numpy(), np.stack((road, wide)))
  np.testing.assert_array_equal(fake_warp.inputs["M_inv"].numpy(), np.stack((eye, eye * 2)))
  assert "new_img" in policy.inputs
  assert "tfm" not in policy.inputs
  assert result["stub"].shape == (1, 1)


def test_fused_artifact_without_device_metadata_remains_compatible(monkeypatch):
  artifact = {
    "format_version": modeld.ARTIFACT_FORMAT_VERSION,
    "execution_mode": "fused",
    "run_model": {},
    "compiler": {"tinygrad_commit": modeld.tinygrad_commit()},
  }
  monkeypatch.setattr(modeld, "get_tg_input_devices", lambda *_args, **_kwargs: {"QUEUE_DEV": "AMD"})

  modeld._validate_fused_artifact_device(artifact, external_gpu_active=True)


def test_fused_artifact_accepts_matching_device_metadata(monkeypatch):
  artifact = {
    "execution_mode": "fused",
    "input_devices": {"model": "amd:0"},
  }
  monkeypatch.setattr(modeld, "get_tg_input_devices", lambda *_args, **_kwargs: {"QUEUE_DEV": "AMD"})

  modeld._validate_fused_artifact_device(artifact, external_gpu_active=True)


def test_fused_artifact_accepts_matching_warp_device_metadata(monkeypatch):
  artifact = {
    "execution_mode": "fused",
    "input_devices": {"model": "amd:0", "warp": "QCOM"},
  }
  monkeypatch.setattr(
    modeld,
    "get_tg_input_devices",
    lambda *_args, **_kwargs: {"QUEUE_DEV": "AMD", "WARP_DEV": "QCOM"},
  )

  modeld._validate_fused_artifact_device(artifact, external_gpu_active=True)


def test_fused_artifact_rejects_wrong_device_metadata(monkeypatch):
  artifact = {
    "execution_mode": "fused",
    "input_devices": {"model": "CPU"},
  }
  monkeypatch.setattr(modeld, "get_tg_input_devices", lambda *_args, **_kwargs: {"QUEUE_DEV": "AMD"})

  with pytest.raises(ValueError, match="device mismatch"):
    modeld._validate_fused_artifact_device(artifact, external_gpu_active=True)


def test_fused_artifact_rejects_wrong_warp_device_metadata(monkeypatch):
  artifact = {
    "execution_mode": "fused",
    "input_devices": {"model": "AMD", "warp": "CPU"},
  }
  monkeypatch.setattr(
    modeld,
    "get_tg_input_devices",
    lambda *_args, **_kwargs: {"QUEUE_DEV": "AMD", "WARP_DEV": "QCOM"},
  )

  with pytest.raises(ValueError, match="warp device mismatch"):
    modeld._validate_fused_artifact_device(artifact, external_gpu_active=True)


def test_upstream_precompiled_artifact_accepts_runtime_model_device(monkeypatch):
  artifact = {
    "execution_mode": modeld.UPSTREAM_PRECOMPILED_EXECUTION_MODE,
    "input_specs": {"new_img": ((2, 6, 128, 256), "uint8", "AMD")},
  }
  monkeypatch.setattr(modeld, "get_tg_input_devices", lambda *_args, **_kwargs: {"QUEUE_DEV": "AMD"})

  modeld._validate_fused_artifact_device(artifact, external_gpu_active=True)


def test_upstream_precompiled_artifact_rejects_wrong_runtime_model_device(monkeypatch):
  artifact = {
    "execution_mode": modeld.UPSTREAM_PRECOMPILED_EXECUTION_MODE,
    "input_specs": {"new_img": ((2, 6, 128, 256), "uint8", "CPU")},
  }
  monkeypatch.setattr(modeld, "get_tg_input_devices", lambda *_args, **_kwargs: {"QUEUE_DEV": "AMD"})

  with pytest.raises(ValueError, match="device mismatch"):
    modeld._validate_fused_artifact_device(artifact, external_gpu_active=True)


def test_external_gpu_probe_matches_upstream_retry_loop(monkeypatch):
  from openpilot.system.hardware.chestnut import flash

  calls = []
  results = iter((False, False, True))
  monkeypatch.setattr(flash, "link_up", lambda: calls.append("probe") or next(results))
  monkeypatch.setattr(model_compiler.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))

  model_compiler.wait_for_external_gpu()

  assert calls == ["probe", ("sleep", 1), "probe", ("sleep", 1), "probe"]


def test_external_gpu_compiler_uses_fused_comma_stack(monkeypatch, tmp_path):
  calls = []
  monkeypatch.setattr(model_compiler, "wait_for_external_gpu", lambda: calls.append("probe"))
  monkeypatch.setattr(model_compiler, "external_gpu_compile_command", lambda command: command)

  def fake_run(command, cwd, env, check):
    calls.append((command, cwd, env, check))

  monkeypatch.setattr(model_compiler.subprocess, "run", fake_run)
  source = tmp_path / "big_driving_supercombo.onnx"
  model_compiler.compile_driving(
    "local-test",
    {"driving_supercombo": source},
    "supercombo",
    "v16",
    tmp_path,
    "policy",
    external_gpu=True,
  )

  assert calls[0] == "probe"
  command, _, env, check = calls[1]
  assert check
  assert "--fused" in command
  assert command[command.index("--benchmark-runs") + 1] == "20"
  assert env["DEV"] == "USB+AMD:LLVM"
  assert env["FRAME_DEV"] == "CPU"
  assert env["TC_MIN_GLOBALS"] == "32"
  assert env["WARP_DEV"] == "QCOM"


def test_external_gpu_warmup_runs_a_complete_frame_and_resets(monkeypatch):
  class FakeTensor:
    @staticmethod
    def zeros(shape, **kwargs):
      calls.append(("tensor", shape, kwargs))
      return FakeTensor()

    def realize(self):
      return self

  calls = []
  state = modeld.ModelState.__new__(modeld.ModelState)
  state.fused = False
  state.frame_buf_size = 32
  state.vision_input_names = ["img", "big_img"]
  state._blob_cache = {}
  state._warp_dev = "QCOM"
  state.desire_key = "desire"
  state.prev_desired_curv_key = "prev_desired_curv"
  state.numpy_inputs = {
    "desire": np.zeros((1, 8), dtype=np.float32),
    "traffic_convention": np.zeros((1, 2), dtype=np.float32),
    "action_t": np.zeros((1, 2), dtype=np.float32),
    "prev_desired_curv": np.zeros((1, 5, 1), dtype=np.float32),
  }

  def fake_run(self, bufs, transforms, inputs, prepare_only):
    calls.append((
      "run",
      {key: value.shape for key, value in bufs.items()},
      {key: value.shape for key, value in transforms.items()},
      {key: value.shape for key, value in inputs.items()},
      prepare_only,
    ))
    return {}

  state.run = MethodType(fake_run, state)
  state._reset_state = MethodType(lambda self: calls.append(("reset",)), state)
  monkeypatch.setattr(modeld, "Tensor", FakeTensor)

  state.warmup()

  assert calls == [
    ("tensor", (32,), {"dtype": "uint8", "device": "QCOM"}),
    ("tensor", (32,), {"dtype": "uint8", "device": "QCOM"}),
    (
      "run",
      {"img": (32,), "big_img": (32,)},
      {"img": (3, 3), "big_img": (3, 3)},
      {"desire": (8,), "traffic_convention": (2,), "action_t": (2,)},
      False,
    ),
    ("reset",),
  ]
