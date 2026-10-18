"""Where a frame's steering curvature comes from, and how the told lateral delay reaches that model.

modeld publishes both on starpilotModelV2 (lateralSource, delayInput) for the Honda EPS controller, which sizes its
command delay from them. The source mirrors get_action_from_model's choice exactly:
  actionHead     v14, v15, v16: the model's own action output. It follows the told delay (action_t) only in part:
                 Cinque v3's aim moves ~0.53 s per 1 s of action_t.
  curvatureHead  v9, and pre-tinygrad models that output desired_curvature: the model's own curvature output.
  plan           everything else: the curvature that reaches the plan's heading at the lateral action time. This
                 fork reads the plan at the told action time exactly (no MIN_STABLE_DELAY floor), so a plan model
                 follows the told delay 1:1 whatever its inputs.
"""

ACTION_HEAD = "actionHead"
CURVATURE_HEAD = "curvatureHead"
PLAN = "plan"


def lateral_source(model_output: dict, mlsim: bool, is_v9: bool, is_v14: bool, is_v15: bool, is_v16: bool) -> str:
  if is_v14 or is_v15 or is_v16:
    return ACTION_HEAD
  if is_v9:
    return CURVATURE_HEAD
  if not mlsim and model_output.get('desired_curvature') is not None:
    return CURVATURE_HEAD
  return PLAN


def takes_action_t(model) -> bool:
  """Whether this model is fed action_t (the condition modeld builds its policy inputs with)."""
  return bool(getattr(model, "requires_action_t", False) or "action_t" in model.numpy_inputs or
              (model.off_policy_enabled and "action_t" in model.off_policy_numpy_inputs))


def delay_input(model) -> str:
  if takes_action_t(model):
    return "actionT"
  if "lateral_control_params" in model.numpy_inputs:
    return "lateralControlParams"
  return "none"
