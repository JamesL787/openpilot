"""How modeld uses the seam, pinned structurally: the order of the calls, what only runs for a local model, what a handover
resets. These read the source; they are the guard against a merge that moves a line, not a substitute for a drive."""
import ast
from pathlib import Path


SRC = (Path(__file__).resolve().parents[3] / "selfdrive/modeld/modeld.py").read_text()
TREE = ast.parse(SRC)
MAIN = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "main")


def calls_in_order(fn):
  """(lineno, 'a.b.c' dotted name) of every call in `fn`, in source order."""
  out = []
  for n in ast.walk(fn):
    if isinstance(n, ast.Call):
      out.append((n.lineno, ast.unparse(n.func)))
  return sorted(out)


def line_of(fn, dotted):
  return next(line for line, name in calls_in_order(fn) if name == dotted)


def test_the_link_is_decided_before_the_process_goes_realtime():
  assert line_of(MAIN, "jetlink_adapter.prepare") < line_of(MAIN, "config_realtime_process")


def test_the_join_comes_after_the_local_model_is_loaded_and_not_before_runtime_params_are_set():
  assert line_of(MAIN, "set_runtime_model_params") < line_of(MAIN, "jetlink_runner.attach")


def test_the_warp_pickle_gets_its_own_buffers_beside_the_loaded_model():
  assert line_of(MAIN, "_isolate_next_model_artifact_load") < line_of(MAIN, "jetlink_runner.attach")


def test_a_chestnut_or_model_laboratory_path_never_reaches_the_attach():
  attach_if = next(n for n in ast.walk(MAIN) if isinstance(n, ast.If) and "jetlink_prepared" in ast.unparse(n.test)
                   and "jetlink_runner.attach" in ast.unparse(n))
  guard = next(n for n in ast.walk(attach_if) if isinstance(n, ast.If) and "usbgpu_present_now" in ast.unparse(n.test))
  names = {n.id for n in ast.walk(guard.test) if isinstance(n, ast.Name)}
  assert {"usbgpu_present_now", "external_gpu_requested", "model_lab_requested", "external_gpu_active"} <= names
  # the guarded branch is the refusal; the attach is in its else
  assert "jetlink_runner.attach" not in "".join(ast.unparse(s) for s in guard.body)
  assert "jetlink_runner.attach" in "".join(ast.unparse(s) for s in guard.orelse)


def test_control_is_handed_over_before_every_run_and_after_the_blinker_is_known():
  set_control = line_of(MAIN, "model.set_control")
  run_lines = [line for line, name in calls_in_order(MAIN) if name == "model.run"]
  assert set_control < min(run_lines)
  blinker = next(n.lineno for n in ast.walk(MAIN) if isinstance(n, ast.Assign) and ast.unparse(n.targets[0]) == "blinker_on")
  assert blinker < set_control


def test_the_gate_reads_the_engagement_services_it_subscribes_to():
  assert '"starpilotCarState"' in SRC and "jetlink_adapter.in_control(sm" in SRC
  for service in ("carState", "carControl", "starpilotCarState"):
    from openpilot.starpilot import jetlink_adapter as ja
    assert service in ja.IN_CONTROL


def test_a_handover_reruns_the_drop_filter_warmup_so_its_own_stall_cannot_hand_it_back():
  handover = next(n for n in ast.walk(MAIN) if isinstance(n, ast.If) and "model.handovers != handovers_before" in ast.unparse(n.test))
  text = ast.unparse(handover)
  assert "run_count = 0" in text and "frame_dropped_filter.x = 0.0" in text and "frame_drop_ratio = 0.0" in text
  # the warm-up that run_count = 0 re-arms is the one that holds the filter at zero
  warmup = next(n for n in ast.walk(MAIN) if isinstance(n, ast.If) and ast.unparse(n.test) == "run_count < 10")
  assert "frame_dropped_filter.x = 0.0" in ast.unparse(warmup)


def test_a_backend_change_resets_the_rolling_publish_state_and_the_runtime_params():
  changed = next(n for n in ast.walk(MAIN) if isinstance(n, ast.If) and "jetlink_state.backend_changed" in ast.unparse(n.test))
  text = ast.unparse(changed)
  assert "publish_state = PublishState()" in text and "_jetlink_publish_runtime" in text


def test_the_backend_is_published_in_the_status_message():
  assert "_fill_jetlink_status(starpilot_modelv2_send.starpilotModelV2, jetlink_state)" in SRC


def test_the_persisted_model_selection_is_never_pointed_at_the_external_model():
  fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "_jetlink_publish_runtime")
  remote_branch = next(n for n in ast.walk(fn) if isinstance(n, ast.If) and "JETLINK" in ast.unparse(n.test))
  written = [ast.literal_eval(c.args[0]) for c in ast.walk(ast.Module(body=remote_branch.body, type_ignores=[]))
             if isinstance(c, ast.Call) and ast.unparse(c.func) == "proxy.put" and isinstance(c.args[0], ast.Constant)]
  assert set(written) == {"ModelVersion", "DrivingModelVersion", "DrivingModelName"}
  assert "Model" not in written and "DrivingModel" not in written


def test_param_writes_on_the_frame_loop_do_not_wait_for_the_disk():
  fn = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "_NonBlockingParams")
  assert "put_nonblocking" in ast.unparse(fn)


def test_the_local_failure_path_is_unchanged_for_a_jetlink_runner():
  """A local-model exception still ends modeld exactly as before: the only external_gpu fallback is for Chestnut."""
  handler = next(n for n in ast.walk(MAIN) if isinstance(n, ast.ExceptHandler) and "external_gpu_active or small_model is None" in ast.unparse(n))
  assert "raise" in ast.unparse(handler)


def test_the_model_message_exposes_the_runner_through_its_modelstate_surface_only():
  from openpilot.starpilot.jetlink_adapter.runner import JetlinkRunner
  # every attribute modeld's loop reads off `model`
  read = {n.attr for n in ast.walk(MAIN) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "model"}
  allowed_extra = {"set_control", "snapshot", "profile", "local_model", "handovers", "run", "warmup", "last_warp_output",
                   "is_v9", "is_v14", "is_v15", "is_v16", "mlsim", "model_id", "policy_generation", "can_prepare_only",
                   "uses_external_gpu"}
  missing = {a for a in read if a in allowed_extra and not hasattr(JetlinkRunner, a) and a not in ("warmup", "model_id")}
  assert not missing, missing
