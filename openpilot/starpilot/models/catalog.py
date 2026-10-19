"""Reviewed local driving-model catalog. This module never loads model artifacts."""

from dataclasses import dataclass, replace
from functools import lru_cache
import json
from pathlib import Path


BUNDLED_CURRENT = "bundled-current"
# Personal branch: the vendored tinygrad is comma's 02e698160e, so StarPilot's published (9d0446a4) artifacts cannot
# load here. The built-in small model is comma's own (master driving_supercombo.onnx, sha 65a08adc), compiled on a
# device for this pin with starpilot/models/compile.py; locally compiled models are listed in the models root's catalog.json.
DEFAULT_SMALL = "comma-small-65a08adc"
DEFAULT_SMALL_NAME = "comma small model (65a08adc)"
DEFAULT_SMALL_SHA256 = "856b1a2f7a79465b9256c361bd7ce43982d57d8adc8603a0ec62dc4006efdbdb"  # QCOM, compiled on the comma 2026-10-18; behavior v12
DEFAULT_SMALL_SIZE = 74526562
GENERATION = "v26"
COMPILER_REVISION = "02e698160eed1751738212144a7ea2cfb160b3f1"
STARPILOT_COMPILER_REVISION = "9d0446a4ba8a532c8b674fb6ad795af015cd9dcf"  # what StarPilot's published catalog targets
ARTIFACT_ABI = "tinygrad_single_v1_arena"
CATALOG_PATH = Path(__file__).with_name("catalog-v26.json")


@dataclass(frozen=True)
class ModelEntry:
  model_id: str
  name: str
  source_sha256: str
  source_path: str
  compiler_revision: str
  artifact_abi: str
  selectable: bool
  version: str = "current"
  uses_external_gpu: bool = False


DEFAULT_SMALL_PATH = f"openpilot/selfdrive/modeld/models/{DEFAULT_SMALL}_driving_tinygrad.pkl"

BUNDLED = tuple(ModelEntry(
  model_id=model_id,
  name=DEFAULT_SMALL_NAME,
  source_sha256=DEFAULT_SMALL_SHA256,
  source_path=DEFAULT_SMALL_PATH,
  compiler_revision=COMPILER_REVISION,
  artifact_abi=ARTIFACT_ABI,
  selectable=True,
  version="v12",  # no action head: like comma's modeld, the action comes from the plan
) for model_id in (BUNDLED_CURRENT, DEFAULT_SMALL))

# StarPilot's published models stay known by name and behavior (old preferences resolve to a clean fallback), but they
# are never selectable: their artifacts target STARPILOT_COMPILER_REVISION.
CATALOG = BUNDLED + tuple(ModelEntry(
  model_id=m["id"], name=m["name"], source_sha256="", source_path="",
  compiler_revision=STARPILOT_COMPILER_REVISION, artifact_abi=ARTIFACT_ABI, selectable=False,
  version=m["version"], uses_external_gpu=bool(m.get("uses_external_gpu", False)),
) for m in json.loads(CATALOG_PATH.read_text())["models"] if m["id"] != DEFAULT_SMALL)

BY_ID = {entry.model_id: entry for entry in CATALOG}


def _document_identity(path: Path) -> tuple:
  try:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
  except OSError:
    return ()


@lru_cache(maxsize=8)
def _cached_entries(root: Path, identities: tuple) -> tuple[ModelEntry, ...]:
  from openpilot.starpilot.models.manager import catalog
  entries = dict(BY_ID)
  for model_id, row in catalog(root).items():
    # catalog() lists only installable rows (personal branch), so a listed StarPilot ID is a local rebuild for this pin
    entries[model_id] = (replace(BY_ID[model_id], name=row["name"], selectable=True, compiler_revision=COMPILER_REVISION)
                         if model_id in BY_ID else
                         ModelEntry(model_id, row["name"], "", "", COMPILER_REVISION, ARTIFACT_ABI,
                                    True, row["version"], row.get("uses_external_gpu", False)))
  return tuple(entries.values())


def model_entries(root: Path | None = None) -> dict[str, ModelEntry]:
  """Resolve validated cached metadata without mutating the bundled catalog."""
  from openpilot.starpilot.models.manager import ROOT
  root = ROOT if root is None else root
  identities = (_document_identity(CATALOG_PATH), _document_identity(root / "catalog.json"))
  return {entry.model_id: entry for entry in _cached_entries(root, identities)}


def resolve_selection(requested_id: str | None, *, root: Path | None = None) -> ModelEntry:
  """Resolve a saved request; absence means the bundled model, never an unknown ID."""
  model_id = DEFAULT_SMALL if requested_id in (None, BUNDLED_CURRENT) else requested_id
  entries = model_entries(root)
  if not isinstance(model_id, str) or model_id not in entries or not entries[model_id].selectable:
    raise ValueError("unqualified driving-model selection")
  return entries[model_id]
