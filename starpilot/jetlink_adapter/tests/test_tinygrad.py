"""The reset and the warp on real tinygrad (CPU): what only the real thing can show.

Jetlink's in-place reset of the local model is a TinyJit captured at attach time. It clears the GPU queues by identity, so it
has to keep clearing the buffers the model reads on every fallback, with nothing allocated or compiled on the failure frame."""
import json
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import numpy as np
import pytest

from jetlink.openpilot.warp import WARP_INPUT_NAMES, prepare_reset
from openpilot.starpilot import jetlink_adapter
from openpilot.starpilot.jetlink_adapter import runner

REPO = Path(__file__).resolve().parents[3]

INPUT_SHAPES = {
  "input_imgs": (1, 12, 128, 256), "big_input_imgs": (1, 12, 128, 256), "desire": (1, 25, 8), "traffic_convention": (1, 2),
  "lateral_control_params": (1, 2), "prev_desired_curv": (1, 25, 1), "features_buffer": (1, 24, 512),
}


def real_model():
  """A ModelState stand-in over the fork's own queue builders, on tinygrad's CPU device."""
  from openpilot.selfdrive.modeld.compile_modeld import make_supercombo_input_queues
  queues, npy = make_supercombo_input_queues(INPUT_SHAPES, 4, "CPU")
  numpy_inputs = {"desire": np.zeros(INPUT_SHAPES["desire"], np.float32), "lateral_control_params": np.zeros(2, np.float32),
                  "prev_desired_curv": np.zeros(INPUT_SHAPES["prev_desired_curv"], np.float32)}
  model = types.SimpleNamespace(
    road_key="input_imgs", wide_key="big_input_imgs", desire_key="desire", vision_input_names=["input_imgs", "big_input_imgs"],
    input_queues=queues, npy=npy, numpy_inputs=numpy_inputs, prev_desire=np.zeros(8, np.float32),
    full_prev_desired_curv=np.zeros((1, 100, 1), np.float32), pin_buffers=lambda: None, unpin_buffers=lambda: None)
  return model


def gpu_queues(model):
  return {k: q for k, q in model.input_queues.items() if q.device != "NPY"}


class TestInPlaceReset:
  def test_it_clears_every_queue_and_host_array_on_repeated_fallbacks_without_replacing_any(self):
    model = real_model()
    local = runner.LocalRunner(model)
    assert set(gpu_queues(model)) == {"img_q", "big_img_q", "feat_q", "desire_q"}
    queue_ids = {k: id(v) for k, v in model.input_queues.items()}
    buffers = {k: q.uop.base.buffer for k, q in gpu_queues(model).items()}
    reset = prepare_reset(local)

    for _ in range(3):
      for q in gpu_queues(model).values():
        q.assign(7).realize()
      for array in local.numpy_inputs.values():
        array.fill(3)
      model.prev_desire.fill(1)
      reset()
      assert {k: id(v) for k, v in model.input_queues.items()} == queue_ids
      assert local.buffers_intact()
      assert {k: q.uop.base.buffer for k, q in gpu_queues(model).items()} == buffers
      for name, q in gpu_queues(model).items():
        assert not q.numpy().any(), name
      assert not model.prev_desire.any()
      assert not model.full_prev_desired_curv.any()
      assert not model.npy["prev_feat"].any() and not model.npy["desire"].any()
      assert not model.numpy_inputs["prev_desired_curv"].any()
      packed = model.input_queues["packed_npy_inputs"].numpy()
      assert not packed.any()                          # the NPY tensor the policy reads is the same memory the views clear

  def test_the_models_own_reset_would_break_it_and_is_refused_once_attached(self):
    """ModelState._reset_state allocates new queues. After attach that would leave the reset clearing buffers nothing
    reads, so the method refuses (selfdrive/modeld/modeld.py: pin_buffers)."""
    import ast
    tree = ast.parse((REPO / "selfdrive/modeld/modeld.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ModelState")
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_reset_state")
    first = ast.unparse(fn.body[0])
    assert "_buffers_pinned" in first and "raise" in ast.unparse(fn.body[0])
    assert {"pin_buffers", "unpin_buffers"} <= {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}

  def test_the_names_jetlinks_reset_reads_are_still_the_model_states(self):
    import ast
    tree = ast.parse((REPO / "selfdrive/modeld/modeld.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ModelState")
    assigned = {n.attr for n in ast.walk(cls) if isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
                and isinstance(n.value, ast.Name) and n.value.id == "self"}
    needed = {"input_queues", "npy", "numpy_inputs", "prev_desire", "road_key", "wide_key", "desire_key", "vision_input_names",
              "full_prev_desired_curv", "off_policy_enabled", "off_policy_numpy_inputs", "can_prepare_only", "model_id",
              "policy_generation", "mlsim", "is_v9", "is_v14", "is_v15", "is_v16"}
    assert needed <= assigned, needed - assigned


# The warp is built and called in its own process on tinygrad's CPU device: a Metal device on a Mac cannot take a camera
# buffer by pointer (Tensor.from_blob), and the device is fixed at the first use in a process.
WARP_SCRIPT = textwrap.dedent('''
  import json, sys, tempfile
  from pathlib import Path
  from unittest import mock
  import numpy as np

  from openpilot.starpilot import jetlink_adapter
  jetlink_adapter.vendor_on_path()
  from jetlink.openpilot.warp import WARP_INPUT_NAMES, Warp, Warps, call_warp, compile_warp, init_device

  CAM, MODEL = (int(sys.argv[1]), int(sys.argv[2])), (512, 256)
  tmp = Path(tempfile.mkdtemp())
  op = jetlink_adapter.adapter()
  op.warp_path = lambda *geometry: tmp / "warp.pkl"
  log = mock.MagicMock()
  init_device(log)
  found = {"init_failed": log.exception.called}

  graph, size = op.make_warp(*CAM, *MODEL)
  compile_warp(graph, size, op.warp_path())
  jit = Warps(op).load(*CAM, *MODEL)                        # the check modeld makes: captured, and the call convention
  found["names"] = list(jit.captured.expected_names)
  face = op.model_face()
  found["frame_size_matches"] = size == face.frame_size(*CAM)

  # run the loaded pickle on two noise frames and compare with the graph called directly
  from tinygrad.tensor import Tensor
  rng = np.random.default_rng(1)
  frames = [rng.integers(0, 256, size, dtype=np.uint8) for _ in range(2)]
  tfm = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], np.float32)
  big_tfm = np.array([[0.9, 0.0, 10.0], [0.0, 0.9, 5.0], [0.0, 0.0, 1.0]], np.float32)
  blobs = [Tensor.from_blob(f.ctypes.data, (size,), dtype="uint8", device=jit.captured.ret.uop.base.buffer.device).realize() for f in frames]
  via_pickle = call_warp(jit, Tensor(tfm, device="NPY"), Tensor(big_tfm, device="NPY"), blobs[0], blobs[1]).numpy()
  direct = graph(Tensor(tfm, device="NPY"), Tensor(big_tfm, device="NPY"), blobs[0], blobs[1]).numpy()
  found.update(shape=list(via_pickle.shape), dtype=str(via_pickle.dtype), nbytes=int(via_pickle.nbytes),
               same_as_direct=bool(np.array_equal(via_pickle, direct)), nonconstant=bool(via_pickle.std() > 1.0))
  print("RESULT" + json.dumps(found))
''')


@pytest.mark.parametrize("cam", [(1928, 1208), (1344, 760)])
def test_the_warp_builds_loads_and_runs_from_the_forks_graph_on_cpu(cam):
  """make_warp -> compile_warp -> pickle -> Warps.load -> the call every frame makes, for both cameras. This does NOT
  qualify the QCOM pickle: the kernels are the CPU's here. It proves the graph, the output layout and the call convention."""
  env = {"PYTHONPATH": jetlink_adapter.pythonpath(str(REPO)), "DEV": "CPU", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
         "HOME": str(Path.home())}
  out = subprocess.run([sys.executable, "-c", WARP_SCRIPT, str(cam[0]), str(cam[1])], capture_output=True, text=True, env=env,
                       cwd=REPO, timeout=600)
  line = next((ln for ln in out.stdout.splitlines() if ln.startswith("RESULT")), None)
  assert line, (out.stdout[-1500:], out.stderr[-3000:])
  found = json.loads(line[len("RESULT"):])
  assert found["names"] == WARP_INPUT_NAMES
  assert found["frame_size_matches"]
  assert found["shape"] == [2, 6, 128, 256] and found["dtype"] == "uint8" and found["nbytes"] == 393216
  assert found["same_as_direct"] and found["nonconstant"]
