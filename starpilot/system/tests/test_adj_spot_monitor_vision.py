from pathlib import Path

import numpy as np

from starpilot.system.adj_spot_monitor_vision import VASMDaemon
from starpilot.system.adj_spot_monitor_vision_inference import MODEL_INPUT_SIZE, V_ASM_MODEL_PATH, VASMInference


class FakeParams:
  def __init__(self, config=None):
    self.config = config or {}

  def get(self, key):
    assert key == "VASMAnnotationConfig"
    return self.config


class FakeMemoryParams:
  def __init__(self):
    self.values = {}

  def put(self, key, value):
    self.values[key] = value


class FakeInference:
  def __init__(self):
    self.loaded = []
    self.reset_count = 0

  def load_config(self, config):
    self.loaded.append(config)

  def reset_state(self):
    self.reset_count += 1


def test_inference_geometry_supports_single_annotated_side():
  inference = VASMInference(Path("unused.onnx"))
  inference.load_config({
    "width": 200,
    "height": 100,
    "poly_left": [[10, 10], [80, 10], [80, 80], [10, 80]],
    "poly_right": [],
  })

  inference._prepare_geometry(100, 200)

  assert inference.configured_sides == ("left",)
  assert inference.bboxes["left"] is not None
  assert inference.bboxes["right"] is None


def test_model_loads_with_repo_inference_backend():
  inference = VASMInference(V_ASM_MODEL_PATH)

  assert inference.load(), inference.last_error
  inference.net.setInput(np.zeros((1, 3, MODEL_INPUT_SIZE, MODEL_INPUT_SIZE), dtype=np.float32))

  out = inference.net.forward()
  # Supports both tri-class (1, 3) master model and legacy binary (1, 2)
  assert out.shape in ((1, 3), (1, 2)), out.shape


def test_model_runs_from_nv12_camera_frame():
  inference = VASMInference(V_ASM_MODEL_PATH)
  assert inference.load(), inference.last_error
  inference.load_config({
    "width": MODEL_INPUT_SIZE,
    "height": MODEL_INPUT_SIZE,
    "poly_left": [[0, 0], [MODEL_INPUT_SIZE, 0], [MODEL_INPUT_SIZE, MODEL_INPUT_SIZE], [0, MODEL_INPUT_SIZE]],
    "poly_right": [],
  })
  nv12 = np.zeros((MODEL_INPUT_SIZE * 3 // 2, MODEL_INPUT_SIZE), dtype=np.uint8)

  assert inference.update(nv12, MODEL_INPUT_SIZE, MODEL_INPUT_SIZE, 0.5, 0.85, 0.05, "left") == (False, False)


def test_classifier_output_maps_class_1_confidence():
  inference = VASMInference(Path("unused.onnx"))
  inference.load_config({
    "width": 100, "height": 100,
    "poly_left": [[0, 0], [100, 0], [100, 100], [0, 100]],
    "poly_right": [],
  })
  inference._prepare_geometry(100, 100)

  class FakeNet:
    def setInput(self, blob):
      pass

    def forward(self):
      # Tri-class output: [0_nocar, 1_car, 2_distant_or_rear]
      return np.array([[0.05, 0.95, 0.00]], dtype=np.float32)

  inference.net = FakeNet()
  inference._valid = True
  left_active, right_active = inference.update(
    np.zeros((150, 100), dtype=np.uint8), 100, 100, 0.5, 0.85, 0.05, "left"
  )
  assert inference.left_confidence == np.float32(0.95)
  assert left_active and not right_active


def test_annotation_changes_reload_without_process_restart():
  first = {"width": 200, "height": 100, "poly_left": [[1, 1], [10, 1], [10, 10]], "poly_right": []}
  second = {"width": 200, "height": 100, "poly_left": [], "poly_right": [[20, 1], [30, 1], [30, 10]]}
  daemon = VASMDaemon.__new__(VASMDaemon)
  daemon.params = FakeParams(first)
  daemon.inference = FakeInference()
  daemon._annotation_config = object()
  daemon._annotation_loaded = False

  assert daemon._load_annotation_config()
  assert not daemon._load_annotation_config()
  daemon.params.config = second
  assert daemon._load_annotation_config()

  assert daemon.inference.loaded == [first, second]


def test_publish_writes_freshness_and_maps_camera_sides_to_ui_sides():
  daemon = VASMDaemon.__new__(VASMDaemon)
  daemon.params_memory = FakeMemoryParams()
  daemon._last_pub_left = False
  daemon._last_pub_right = False
  daemon._last_pub_left_conf = -1.0
  daemon._last_pub_right_conf = -1.0
  daemon._last_update_at = 0.0

  daemon._publish(True, False, 0.9, 0.1, 123, updated_at=50.0)

  assert daemon.params_memory.values["VASMLastUpdateMonoTime"] == "50.0"
  assert daemon.params_memory.values["VASMLeftActive"] == "0"
  assert daemon.params_memory.values["VASMRightActive"] == "1"

class _Lead:
  def __init__(self, status=False, dRel=0.0, vRel=0.0, radarTrackId=-1):
    self.status, self.dRel, self.vRel, self.radarTrackId = status, dRel, vRel, radarTrackId


class _FakeSM:
  def __init__(self, left=None, right=None, left_blinker=False, right_blinker=False, v_ego=30.0):
    from types import SimpleNamespace
    self.valid = {"starpilotRadarState": True, "carState": True}
    self.msgs = {"starpilotRadarState": SimpleNamespace(leadLeft=left or _Lead(), leadRight=right or _Lead()),
                 "carState": SimpleNamespace(leftBlinker=left_blinker, rightBlinker=right_blinker, vEgo=v_ego)}

  def __getitem__(self, key):
    return self.msgs[key]


def _assist_daemon(radar_assist=True):
  from types import SimpleNamespace
  from openpilot.starpilot.common.vasm_assist import PassHold

  class Memory(FakeMemoryParams):
    def get(self, key):
      return self.values.get(key)

  daemon = VASMDaemon.__new__(VASMDaemon)
  daemon.params_memory = Memory()
  daemon._radar_assist = radar_assist
  daemon.pass_hold = PassHold()
  daemon.inference = SimpleNamespace(left_active=False, right_active=False)
  daemon._hold = {"left": False, "right": False}
  daemon._focus_image = set()
  daemon._last_pub_left = (False, False)
  daemon._last_pub_right = (False, False)
  daemon._last_pub_left_conf = -1.0
  daemon._last_pub_right_conf = -1.0
  daemon._last_update_at = 0.0
  return daemon


def test_d118_pass_hold_marks_the_car_side_occupied_while_the_camera_sees_nothing():
  daemon = _assist_daemon()
  daemon.sm = _FakeSM(left=_Lead(True, 3.0, -4.0, 7))
  daemon._update_assist(0.0)
  daemon.sm = _FakeSM()
  daemon._update_assist(0.1)
  assert daemon._hold == {"left": True, "right": False}
  daemon._publish(False, False, 0.1, 0.1, 1, updated_at=0.1)
  assert daemon.params_memory.values["VASMLeftActive"] == "1", "car-frame left, not mirrored"
  assert daemon.params_memory.values["VASMRightActive"] == "0"

  daemon._update_assist(10.0)
  daemon._publish(False, False, 0.1, 0.1, 1, updated_at=10.0)
  assert daemon.params_memory.values["VASMLeftActive"] == "0", "a hold ending is published even with no camera change"


def test_d118_focus_is_image_frame_and_off_means_no_assist():
  daemon = _assist_daemon()
  daemon.sm = _FakeSM(left_blinker=True)
  daemon._update_assist(0.0)
  assert daemon._focus_image == {"right"}, "car left is image right on the driver camera"
  daemon.params_memory.put("NavPassingPrompt", '{"armed": true, "side": "right"}')
  daemon.sm = _FakeSM()
  daemon._update_assist(0.1)
  assert daemon._focus_image == {"left"}

  off = _assist_daemon(radar_assist=False)
  off.sm = _FakeSM(left=_Lead(True, 3.0, -4.0, 7), left_blinker=True)
  off._update_assist(0.0)
  off.sm = _FakeSM()
  off._update_assist(0.1)
  assert off._hold == {"left": False, "right": False} and off._focus_image == set()


def test_d121_camera_on_the_car_side_feeds_the_semi_hold():
  daemon = _assist_daemon()
  daemon.sm = _FakeSM(right=_Lead(True, 8.0, -4.0, 44))
  daemon._update_assist(0.0)
  daemon.sm = _FakeSM()
  t = 0.05
  while t < 2.0:  # plain hold covers the hand-off
    daemon._update_assist(t)
    t += 0.05
  daemon.inference.left_active = True  # image left = car right
  while t < 8.0:  # 6 s at 4 m/s: 24 m of trailer and tractor
    daemon._update_assist(t)
    t += 0.05
  daemon.inference.left_active = False
  daemon._update_assist(t)
  assert daemon._hold["right"] and not daemon._hold["left"], "camera lost the truck, but its front is still beside us"
