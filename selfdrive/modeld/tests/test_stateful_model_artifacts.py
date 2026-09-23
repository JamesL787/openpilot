from pathlib import Path

import numpy as np
import pytest
from tinygrad import Context, Tensor, dtypes

from openpilot.selfdrive.modeld import modeld
from openpilot.selfdrive.modeld.compile_modeld import (
  make_stateful_input_queues,
  make_run_stateful_supercombo,
  stateful_host_shapes,
  stateful_image_shapes,
)


@pytest.fixture
def stateful_metadata():
  return {
    "input_shapes": {
      "new_img": (2, 6, 4, 8),
      "desire": (8,),
      "traffic_convention": (1, 2),
      "action_t": (1, 2),
      "state_img_q": (2, 1, 6, 4, 8),
      "state_desire_q": (4, 1, 8),
      "state_feat_q": (2, 1, 16),
    },
    "output_shapes": {
      "next_state_img_q": (2, 1, 6, 4, 8),
      "next_state_desire_q": (4, 1, 8),
      "next_state_feat_q": (2, 1, 16),
    },
    "input_dtypes": {
      "state_img_q": "uint8",
      "state_desire_q": "float16",
      "state_feat_q": "float16",
    },
    "state_pairs": {
      "state_img_q": "next_state_img_q",
      "state_desire_q": "next_state_desire_q",
      "state_feat_q": "next_state_feat_q",
    },
  }


def test_stateful_model_exposes_road_wide_crop_abi(stateful_metadata):
  assert stateful_image_shapes(stateful_metadata) == {
    "img": (1, 6, 4, 8),
    "big_img": (1, 6, 4, 8),
  }
  assert stateful_host_shapes(stateful_metadata) == {
    "desire": (8,),
    "traffic_convention": (1, 2),
    "action_t": (1, 2),
  }


def test_stateful_model_allocates_packed_inputs_and_persistent_state(stateful_metadata):
  queues, npy = make_stateful_input_queues(stateful_metadata, "CPU")

  assert set(("packed_npy_inputs", *stateful_metadata["state_pairs"])) <= set(queues)
  assert queues["packed_npy_inputs"].shape == (12,)
  assert npy["desire"].shape == (8,)
  assert npy["traffic_convention"].shape == (1, 2)
  assert npy["action_t"].shape == (1, 2)
  assert queues["state_img_q"].shape == stateful_metadata["input_shapes"]["state_img_q"]
  assert queues["state_desire_q"].shape == stateful_metadata["input_shapes"]["state_desire_q"]
  assert queues["state_feat_q"].shape == stateful_metadata["input_shapes"]["state_feat_q"]
  assert all(np.count_nonzero(queue.numpy()) == 0 for name, queue in queues.items() if name.startswith("state_"))


@pytest.mark.parametrize("bad_shape", [(2, 3, 4, 8), (6, 4, 8), (2, 6, 4)])
def test_stateful_model_rejects_unsupported_image_shape(stateful_metadata, bad_shape):
  stateful_metadata["input_shapes"]["new_img"] = bad_shape
  with pytest.raises(ValueError, match="Unsupported stateful image shape"):
    stateful_image_shapes(stateful_metadata)


def test_stateful_model_rejects_mismatched_state_pair_shape(stateful_metadata):
  stateful_metadata["output_shapes"]["next_state_feat_q"] = (1,)
  with pytest.raises(ValueError, match="State shape mismatch"):
    make_stateful_input_queues(stateful_metadata, "CPU")


def test_stateful_runner_advances_onnx_state_pairs(stateful_metadata):
  class FakeRunner:
    graph_inputs = {
      "new_img": type("Spec", (), {"dtype": dtypes.uint8})(),
      "desire": type("Spec", (), {"dtype": dtypes.float32})(),
      "traffic_convention": type("Spec", (), {"dtype": dtypes.float32})(),
      "action_t": type("Spec", (), {"dtype": dtypes.float32})(),
      "state_img_q": type("Spec", (), {"dtype": dtypes.uint8})(),
      "state_desire_q": type("Spec", (), {"dtype": dtypes.float16})(),
      "state_feat_q": type("Spec", (), {"dtype": dtypes.float16})(),
    }

    def __call__(self, inputs):
      assert inputs["new_img"].shape == (2, 6, 4, 8)
      return {
        "outputs": Tensor(np.array([1.0], dtype=np.float32)),
        **{
          next_name: inputs[name] + 1
          for name, next_name in stateful_metadata["state_pairs"].items()
        },
      }

  with Context(DEV="CPU"):
    queues, _npy = make_stateful_input_queues(stateful_metadata, "CPU")
    run_policy = make_run_stateful_supercombo(FakeRunner(), stateful_metadata)
    warped = Tensor(np.zeros((2, 6, 4, 8), dtype=np.uint8)).realize()
    output, = run_policy(
      warped=warped,
      packed_npy_inputs=queues["packed_npy_inputs"],
      **{name: queues[name] for name in stateful_metadata["state_pairs"]},
    )

    assert output.dtype == dtypes.float32
    for name in stateful_metadata["state_pairs"]:
      np.testing.assert_array_equal(queues[name].numpy(), 1)


def test_model_state_initializes_and_resets_stateful_history(monkeypatch, stateful_metadata):
  policy_inputs = {
    name: tuple(shape)
    for name, shape in stateful_metadata["input_shapes"].items()
    if name != "new_img" and name not in stateful_metadata["state_pairs"]
  }
  artifact = {
    "format_version": modeld.LEGACY_ARTIFACT_FORMAT_VERSION,
    "execution_mode": "split",
    "model_type": "supercombo",
    "metadata": {"model": {**stateful_metadata, "output_slices": {}}},
    "policy_order": [],
    "frame_skip": 1,
    "image_history_pipeline": modeld.IMAGE_HISTORY_IN_POLICY,
    "warp_input_keys": modeld.LEGACY_WARP_INPUTS,
    "policy_input_keys": ("packed_npy_inputs", *stateful_metadata["state_pairs"]),
    "run_policy": lambda **_kwargs: (),
    (1344, 760): object(),
  }
  monkeypatch.setattr(modeld, "_load_model_artifact", lambda _path: artifact)
  monkeypatch.setattr(modeld, "file_chunked_exists", lambda _path: True)
  monkeypatch.setattr(modeld, "model_uses_external_gpu", lambda _model_id: False)
  monkeypatch.setattr(
    modeld,
    "get_tg_input_devices",
    lambda *_args, **_kwargs: {"QUEUE_DEV": "CPU", "WARP_DEV": "CPU"},
  )

  state = modeld.ModelState(
    1344,
    760,
    model_id_override="synthetic-stateful",
    write_model_version=False,
    model_version_override="v16",
    model_path_override=Path("synthetic-stateful.pkl"),
  )

  assert state.onnx_history
  assert state.road_key == "img"
  assert state.wide_key == "big_img"
  assert state.policy_input_shapes == policy_inputs
  state.input_queues["state_feat_q"].assign(1).realize()
  state._reset_state()
  assert np.count_nonzero(state.input_queues["state_feat_q"].numpy()) == 0
