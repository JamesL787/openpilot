"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import hashlib
import os
import pickle
import numpy as np

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from cereal import custom
from openpilot.sunnypilot.models.constants import Meta, MetaTombRaider, MetaSimPose
from openpilot.system.hardware.hw import Paths
from pathlib import Path

# see the README.md for more details on the model selector versioning
CURRENT_SELECTOR_VERSION = 15
REQUIRED_MIN_SELECTOR_VERSION = 14


CUSTOM_MODEL_PATH = Paths.model_root()
METADATA_PATH = Path(__file__).parent / '../models/supercombo_metadata.pkl'

ModelManager = custom.ModelManagerSP


def _compute_hash(file_path: str) -> str | None:
  from openpilot.common.file_chunker import read_file_chunked

  try:
    return hashlib.sha256(read_file_chunked(file_path)).hexdigest().lower()
  except FileNotFoundError:
    return None


async def verify_file(file_path: str, expected_hash: str) -> bool:
  """Verifies file hash against expected hash."""
  file_hash = _compute_hash(file_path)
  return file_hash == expected_hash.lower() if file_hash else False


def _verify_file(file_path: str, expected_hash: str) -> bool:
  file_hash = _compute_hash(file_path)
  return file_hash == expected_hash.lower() if file_hash else False


def _bundle_value(bundle: dict, *keys: str, default=None):
  if not isinstance(bundle, dict):
    return default
  for key in keys:
    if (value := bundle.get(key)) is not None:
      return value
  return default


def _enum_value(enum_type, value):
  if isinstance(value, str):
    return getattr(enum_type, value, value)
  return value


def _download_uri_from_dict(download_uri_data: dict) -> custom.ModelManagerSP.DownloadUri:
  download_uri = custom.ModelManagerSP.DownloadUri()
  download_uri.uri = _bundle_value(download_uri_data, "uri", "url", default="")
  download_uri.sha256 = _bundle_value(download_uri_data, "sha256", default="")
  return download_uri


def _artifact_from_dict(artifact_data: dict) -> custom.ModelManagerSP.Artifact:
  artifact = custom.ModelManagerSP.Artifact()
  artifact.fileName = _bundle_value(artifact_data, "fileName", "file_name", default="")
  artifact.downloadUri = _download_uri_from_dict(_bundle_value(artifact_data, "downloadUri", "download_uri", default={}))
  return artifact


def _model_from_dict(model_data: dict) -> custom.ModelManagerSP.Model:
  model = custom.ModelManagerSP.Model()
  model.type = _enum_value(custom.ModelManagerSP.Model.Type, _bundle_value(model_data, "type", default=custom.ModelManagerSP.Model.Type.supercombo))
  model.artifact = _artifact_from_dict(_bundle_value(model_data, "artifact", default={}))
  if metadata_data := _bundle_value(model_data, "metadata", default=None):
    model.metadata = _artifact_from_dict(metadata_data)
  return model


def _override_from_dict(override_data: dict) -> custom.ModelManagerSP.Override:
  override = custom.ModelManagerSP.Override()
  override.key = _bundle_value(override_data, "key", default="")
  override.value = _bundle_value(override_data, "value", default="")
  return override


def _bundle_from_dict(bundle_data: dict) -> custom.ModelManagerSP.ModelBundle:
  bundle = custom.ModelManagerSP.ModelBundle()
  bundle.index = int(_bundle_value(bundle_data, "index", default=0))
  bundle.internalName = _bundle_value(bundle_data, "internalName", "short_name", default="")
  bundle.displayName = _bundle_value(bundle_data, "displayName", "display_name", default="")
  bundle.status = _enum_value(custom.ModelManagerSP.DownloadStatus, _bundle_value(bundle_data, "status", default=custom.ModelManagerSP.DownloadStatus.notDownloading))
  bundle.generation = int(_bundle_value(bundle_data, "generation", default=0))
  bundle.environment = _bundle_value(bundle_data, "environment", default="")
  bundle.runner = _enum_value(custom.ModelManagerSP.Runner, _bundle_value(bundle_data, "runner", default=custom.ModelManagerSP.Runner.stock))
  bundle.is20hz = bool(_bundle_value(bundle_data, "is20hz", "is_20hz", default=False))
  bundle.minimumSelectorVersion = int(_bundle_value(bundle_data, "minimumSelectorVersion", "minimum_selector_version", default=0))
  if ref := _bundle_value(bundle_data, "ref", default=None):
    bundle.ref = ref

  models_data = _bundle_value(bundle_data, "models", default=[])
  if models_data is not None:
    models = bundle.init("models", len(models_data))
    for i, model_data in enumerate(models_data):
      models[i] = _model_from_dict(model_data)

  overrides_data = _bundle_value(bundle_data, "overrides", default={})
  if overrides_data is not None:
    if isinstance(overrides_data, dict):
      overrides = bundle.init("overrides", len(overrides_data))
      for i, (key, value) in enumerate(overrides_data.items()):
        overrides[i] = _override_from_dict({"key": key, "value": value})
    else:
      overrides = bundle.init("overrides", len(overrides_data))
      for i, override_data in enumerate(overrides_data):
        overrides[i] = _override_from_dict(override_data)

  return bundle


def is_bundle_version_compatible(bundle: dict) -> bool:
  """
  Checks whether the model bundle is compatible with the current selector version constraints.

  The bundle specifies a `minimum_selector_version`, which defines the minimum selector version
  required to load the model. This function ensures that:

    1. The model is not too old: the bundle must require at least `REQUIRED_MIN_SELECTOR_VERSION`.
    2. The model is not too new: it must support the current selector version (`CURRENT_SELECTOR_VERSION`).

  This allows the selector to enforce both a minimum and maximum range of supported models,
  even if a model would otherwise be compatible.

  :param bundle: Dictionary containing `minimum_selector_version`, as defined by the model bundle.
  :type bundle: Dict
  :return: True if the selector version is within the accepted range for the bundle; otherwise False.
  :rtype: Bool
  """
  minimum_selector_version = bundle.get("minimum_selector_version", bundle.get("minimumSelectorVersion", 0))
  try:
    minimum_selector_version = int(minimum_selector_version)
  except (TypeError, ValueError):
    minimum_selector_version = 0
  return bool(REQUIRED_MIN_SELECTOR_VERSION <= minimum_selector_version <= CURRENT_SELECTOR_VERSION)


def get_active_bundle(params: Params = None) -> custom.ModelManagerSP.ModelBundle:
  """Gets the active model bundle from cache"""
  if params is None:
    params = Params()

  try:
    if (active_bundle := params.get("ModelManager_ActiveBundle") or {}) and is_bundle_version_compatible(active_bundle):
      return _bundle_from_dict(active_bundle)
  except Exception:
    pass

  return None


def _bundle_artifacts(bundle: custom.ModelManagerSP.ModelBundle) -> list[tuple[str, str]]:
  artifacts: list[tuple[str, str]] = []
  for model in getattr(bundle, 'models', []) or []:
    for artifact in (getattr(model, 'artifact', None), getattr(model, 'metadata', None)):
      if artifact is None or not getattr(artifact, 'fileName', None) or not getattr(artifact, 'downloadUri', None):
        continue
      sha256 = getattr(artifact.downloadUri, 'sha256', None)
      if sha256:
        artifacts.append((artifact.fileName, sha256))
  return artifacts


def _bundle_is_valid_locally(bundle: custom.ModelManagerSP.ModelBundle) -> bool:
  model_root = Paths.model_root()
  return all(_verify_file(os.path.join(model_root, file_name), expected_hash) for file_name, expected_hash in _bundle_artifacts(bundle))


def _bundle_needs_reset(active_bundle: custom.ModelManagerSP.ModelBundle,
                        available_bundles: list[custom.ModelManagerSP.ModelBundle] | None) -> bool:
  if active_bundle is None:
    return False

  if available_bundles is not None:
    matching_bundle = None
    for bundle in available_bundles:
      if getattr(active_bundle, 'ref', None) and getattr(bundle, 'ref', None):
        if active_bundle.ref == bundle.ref:
          matching_bundle = bundle
          break
      elif getattr(active_bundle, 'internalName', None) == getattr(bundle, 'internalName', None):
        matching_bundle = bundle
        break

    if matching_bundle is None:
      return True

    if active_bundle.minimumSelectorVersion != matching_bundle.minimumSelectorVersion:
      return True

    active_runner = getattr(active_bundle, 'runner', None)
    matching_runner = getattr(matching_bundle, 'runner', None)
    if active_runner is not None and matching_runner is not None:
      if getattr(active_runner, 'raw', active_runner) != getattr(matching_runner, 'raw', matching_runner):
        return True

    if set(_bundle_artifacts(active_bundle)) != set(_bundle_artifacts(matching_bundle)):
      return True

  return not _bundle_is_valid_locally(active_bundle)


def validate_active_bundle(params: Params, available_bundles: list[custom.ModelManagerSP.ModelBundle] | None = None) -> None:
  raw_bundle = params.get("ModelManager_ActiveBundle")
  if not raw_bundle:
    return

  try:
    active_bundle = _bundle_from_dict(raw_bundle)
  except Exception:
    cloudlog.warning("Active model bundle could not be decoded; resetting to stock")
    params.remove("ModelManager_ActiveBundle")
    params.put("ModelRunnerTypeCache", int(custom.ModelManagerSP.Runner.stock))
    return

  if _bundle_needs_reset(active_bundle, available_bundles):
    cloudlog.warning("Active model bundle invalid or stale; resetting to stock")
    params.remove("ModelManager_ActiveBundle")
    params.put("ModelRunnerTypeCache", int(custom.ModelManagerSP.Runner.stock))


def get_active_model_runner(params: Params = None, force_check=False) -> custom.ModelManagerSP.Runner:
  """
  Determines and returns the active model runner type, based on provided parameters.
  The function utilizes caching to prevent redundant calculations and checks.

  If the cached "ModelRunnerTypeCache" exists in the provided parameters and `force_check`
  is set to False, the cached value is directly returned. Otherwise, the function determines
  the runner type based on the active model bundle. If a model bundle containing a drive
  model exists, the runner type is derived based on the filename of the drive model.
  Finally, it updates the cache with the determined runner type, if needed.

  :param params: The parameter set used to retrieve caching and runner details. If `None`,
      a default `Params` instance is created internally.
  :type params: Params
  :param force_check: A flag indicating whether to bypass cached results and always
      re-determine the runner type. Defaults to `False`.
  :type force_check: bool
  :return: The determined or cached model runner type.
  :rtype: custom.ModelManagerSP.Runner
  """
  if params is None:
    params = Params()

  if (cached_runner_type := params.get("ModelRunnerTypeCache")) and not force_check:
    if isinstance(cached_runner_type, str) and cached_runner_type.isdigit():
      return int(cached_runner_type)

  runner_type = custom.ModelManagerSP.Runner.stock

  if active_bundle := get_active_bundle(params):
    runner_type = active_bundle.runner.raw

  if cached_runner_type != runner_type:
    params.put("ModelRunnerTypeCache", int(runner_type))

  return runner_type

def _get_model():
  if bundle := get_active_bundle():
    drive_model = next(model for model in bundle.models if model.type == ModelManager.Model.Type.supercombo)
    return drive_model

  return None

def load_metadata():
  metadata_path = METADATA_PATH

  if model := _get_model():
    metadata_path = f"{CUSTOM_MODEL_PATH}/{model.metadata.fileName}"

  with open(metadata_path, 'rb') as f:
    return pickle.load(f)


def prepare_inputs(model_metadata) -> dict[str, np.ndarray]:
  # img buffers are managed in openCL transform code so we don't pass them as inputs
  inputs = {
    k: np.zeros(v, dtype=np.float32).flatten()
    for k, v in model_metadata['input_shapes'].items()
    if 'img' not in k
  }

  return inputs


def load_meta_constants(model_metadata):
  """
  Determines and loads the appropriate meta model class based on the metadata provided. The function checks
  specific keys and conditions within the provided metadata dictionary to identify the corresponding meta
  model class to return.

  :param model_metadata: Dictionary containing metadata about the model. It includes
      details such as input shapes, output slices, and other configurations for identifying
      metadata-dependent meta model classes.
  :type model_metadata: dict
  :return: The appropriate meta model class (Meta, MetaSimPose, or MetaTombRaider)
      based on the conditions and metadata provided.
  :rtype: type
  """
  meta = Meta  # Default Meta

  if 'sim_pose' in model_metadata['input_shapes'].keys():
    # Meta for models with sim_pose input
    meta = MetaSimPose
  else:
    # Meta for Tomb Raider, it does not include sim_pose input but has the same meta slice as previous models
    meta_slice = model_metadata['output_slices']['meta']
    meta_tf_slice = slice(5868, 5921, None)

    if (
            meta_slice.start == meta_tf_slice.start and
            meta_slice.stop == meta_tf_slice.stop and
            meta_slice.step == meta_tf_slice.step
    ):
      meta = MetaTombRaider

  return meta


# The following method(s) are modeld helper methods
def plan_x_idxs_helper(constants, plan, model_output) -> list[float]:
  # times at X_IDXS according to plan.
  LINE_T_IDXS = [np.nan] * constants.IDX_N
  LINE_T_IDXS[0] = 0.0
  plan_x = model_output['plan'][0, :, plan.POSITION][:, 0].tolist()
  for xidx in range(1, constants.IDX_N):
    tidx = 0
    # increment tidx until we find an element that's further away than the current xidx
    while tidx < constants.IDX_N - 1 and plan_x[tidx + 1] < constants.X_IDXS[xidx]:
      tidx += 1
    if tidx == constants.IDX_N - 1:
      # if the plan doesn't extend far enough, set plan_t to the max value (10s), then break
      LINE_T_IDXS[xidx] = constants.T_IDXS[constants.IDX_N - 1]
      break
    # interpolate to find `t` for the current xidx
    current_x_val = plan_x[tidx]
    next_x_val = plan_x[tidx + 1]
    p = (constants.X_IDXS[xidx] - current_x_val) / (next_x_val - current_x_val) if abs(
      next_x_val - current_x_val) > 1e-9 else float('nan')
    LINE_T_IDXS[xidx] = p * constants.T_IDXS[tidx + 1] + (1 - p) * constants.T_IDXS[tidx]
  return LINE_T_IDXS
