import pytest

from openpilot.selfdrive.modeld import modeld


class FakeParams:
  def __init__(self):
    self.values = {}

  def put(self, key, value):
    self.values[key] = value


@pytest.mark.parametrize(("model_output", "dropped_frames", "external_gpu_active", "expected"), [
  (object(), 0, False, True),
  (object(), 1, False, True),
  (object(), 2, False, True),
  (object(), 0, True, True),
  (object(), 1, True, True),
  (object(), 2, True, True),
  (None, 0, False, False),
  (None, 1, True, False),
])
def test_completed_model_output_is_published_after_vipc_drop(model_output, dropped_frames, external_gpu_active, expected):
  assert modeld._should_publish_model_output(model_output, dropped_frames, external_gpu_active) is expected


def test_incompatible_downloaded_model_falls_back_to_builtin(monkeypatch):
  calls = []
  builtin_model = object()

  def load_model(cam_w, cam_h, external_gpu_active, **kwargs):
    calls.append((cam_w, cam_h, external_gpu_active, kwargs.get("model_id_override")))
    if len(calls) == 1:
      raise TypeError("incompatible artifact")
    return builtin_model

  params = FakeParams()
  monkeypatch.setattr(modeld, "ModelState", load_model)
  monkeypatch.setattr(modeld.cloudlog, "exception", lambda *_args, **_kwargs: None)

  assert modeld._load_model_state(1928, 1208, "custom-model", False, params) is builtin_model
  assert calls == [
    (1928, 1208, False, "custom-model"),
    (1928, 1208, False, modeld.BUILTIN_MODEL_KEY),
  ]
  assert params.values == {
    "Model": modeld.BUILTIN_MODEL_KEY,
    "DrivingModel": modeld.BUILTIN_MODEL_KEY,
    "DrivingModelName": modeld.BUILTIN_MODEL_NAME,
  }


def test_builtin_model_load_failure_is_not_hidden(monkeypatch):
  monkeypatch.setattr(modeld, "ModelState", lambda *_args, **_kwargs: (_ for _ in ()).throw(TypeError("bad builtin")))

  with pytest.raises(TypeError, match="bad builtin"):
    modeld._load_model_state(1928, 1208, modeld.BUILTIN_MODEL_KEY, False, FakeParams())


def _drop_ratio_after(drop_steps, n_steps):
  # modeld's dropped-frame filter and ratio, one camera frame dropped at each step in drop_steps
  from openpilot.common.filter_simple import FirstOrderFilter
  from openpilot.selfdrive.modeld.constants import ModelConstants
  f = FirstOrderFilter(0., 10., 1. / ModelConstants.MODEL_FREQ)
  worst = 0.
  for i in range(n_steps):
    x = f.update(1 if i in drop_steps else 0)
    worst = max(worst, x / (1 + x))
  return worst


def test_big_model_drop_gate_forgives_one_dropped_frame():
  assert not modeld._big_model_behind(True, True, _drop_ratio_after({0}, 400))


def test_big_model_drop_gate_trips_on_a_second_drop_within_six_seconds():
  assert modeld._big_model_behind(True, True, _drop_ratio_after({0, 120}, 200))       # 6 s apart


def test_big_model_drop_gate_forgives_drops_seven_seconds_apart():
  assert not modeld._big_model_behind(True, True, _drop_ratio_after({0, 140}, 200))   # 7 s apart


def test_big_model_drop_gate_trips_at_one_skip_in_thirteen():
  # route 000003bb: 52 ms a frame skips about one camera frame in thirteen; the gate trips within a second
  assert modeld._big_model_behind(True, True, _drop_ratio_after(set(range(0, 20, 13)), 20))


def test_big_model_drop_gate_needs_an_external_model_and_a_small_fallback():
  assert not modeld._big_model_behind(False, True, 0.5)
  assert not modeld._big_model_behind(True, False, 0.5)
  assert not modeld._big_model_behind(True, True, modeld.BIG_MODEL_DROP_LIMIT)


class _FakeDevices:
  def __init__(self, names):
    self._opened_devices = set(names)
    self.devs = {n: type("Dev", (), {"pending": {}})() for n in names}

  def __getitem__(self, name): return self.devs[name]


def test_drop_chestnut_forgets_every_pending_wait_on_the_chestnut(monkeypatch):
  fake = _FakeDevices(["AMD", "QCOM", "CPU"])
  amd, qcom, cpu = fake["AMD"], fake["QCOM"], fake["CPU"]
  qcom.pending.update({amd: 7, cpu: 3})
  cpu.pending[amd] = 9
  monkeypatch.setattr(modeld, "Device", fake)
  modeld.drop_chestnut()
  assert qcom.pending == {cpu: 3}   # only the Chestnut's wait goes
  assert cpu.pending == {}


def test_drop_chestnut_without_a_chestnut_is_a_noop(monkeypatch):
  fake = _FakeDevices(["QCOM", "CPU"])
  fake["QCOM"].pending[fake["CPU"]] = 1
  monkeypatch.setattr(modeld, "Device", fake)
  modeld.drop_chestnut()
  assert fake["QCOM"].pending == {fake["CPU"]: 1}
