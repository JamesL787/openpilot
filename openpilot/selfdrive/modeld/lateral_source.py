"""Where a frame's steering curvature comes from (Night Star port of ns-bosch's lateral_source.py, for 7.0's runners).

modeld writes it to the ModelLateralSource param whenever it changes (and logs a modelLateralSource event), for the
Honda EPS controller, which sizes its command delay from
it: a plan read at the told delay exactly needs none, an action head follows the told delay only in part.

  actionHead     v14, v15, v16 catalog models, and any runner whose output carries "action": the model's own action.
                 Cinque v3's aim moves ~0.53 s per 1 s of action_t.
  curvatureHead  v9 catalog models: their own desired_curvature output.
  plan           any other catalog model: runner.action_from_outputs reads the plan at lat_action_t exactly.
  unknown        a plan read through drive_helpers.get_curvature_from_plan (the bundled Chestnut runner, Jetlink's big
                 model), which floors action_t at MIN_STABLE_DELAY 0.3 s, so the told delay does not land it 1:1.
                 The controller keeps the calibration's command delay for unknown.
"""
UNKNOWN = "unknown"
PLAN = "plan"
ACTION_HEAD = "actionHead"
CURVATURE_HEAD = "curvatureHead"
SOURCES = (UNKNOWN, PLAN, ACTION_HEAD, CURVATURE_HEAD)

ACTION_HEAD_VERSIONS = ("v14", "v15", "v16")


def source_for_version(version: str | None) -> str:
  if version in ACTION_HEAD_VERSIONS:
    return ACTION_HEAD
  if version == "v9":
    return CURVATURE_HEAD
  return PLAN if version else UNKNOWN


def lateral_source(model, model_output) -> str:
  """The source modeld's action for this frame was taken from (mirrors how each 7.0 runner builds its action)."""
  from openpilot.starpilot.models.runner import CatalogModelState
  # A joining Jetlink model drives as the small model itself until its big model is ready, so that is a catalog model
  # or the bundled runner here; Jetlink's JetlinkModelState is always the big-model role.
  if isinstance(model, CatalogModelState):
    return source_for_version(model.behavior_version)
  # the bundled Chestnut runner and Jetlink's big model: get_action_from_model
  if model_output is not None and 'action' in model_output:
    return ACTION_HEAD
  return UNKNOWN
