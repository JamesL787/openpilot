#!/usr/bin/env python3
"""Compile staged ONNX sources without installing or selecting the result."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
  "supercombo": ("driving_supercombo", "supercombo"),
  "off-policy": ("driving_off_policy", "off_policy", "offpolicy"),
  "on-policy": ("driving_on_policy", "on_policy", "onpolicy"),
  "policy": ("driving_policy", "policy"),
  "vision": ("driving_vision", "vision"),
}


def source_files(directory: Path, model: str) -> dict[str, Path]:
  selected = directory / model if (directory / model).is_dir() else directory
  found = {}
  for path in sorted(selected.glob("*.onnx")):
    stem = path.stem.lower()
    for component, aliases in COMPONENTS.items():
      if any(stem == alias or stem == f"{model}_{alias}" for alias in aliases):
        if component in found:
          raise ValueError(f"Ambiguous {component} source: {found[component]} and {path}")
        found[component] = path.resolve()
        break
  return found


def driving_compile_args(files: dict[str, Path], requested: str) -> tuple[str, list[str]]:
  selected = "supercombo" if requested == "auto" and "supercombo" in files else requested
  if selected == "supercombo":
    if "supercombo" not in files:
      raise ValueError("Supercombo input requires driving_supercombo.onnx")
    return "supercombo", ["--supercombo-onnx", str(files["supercombo"])]
  if "vision" not in files or not ({"policy", "on-policy"} & files.keys()):
    raise ValueError("Split input requires driving_vision.onnx and driving_policy.onnx or driving_on_policy.onnx")
  result = ["--vision-onnx", str(files["vision"])]
  primary = files.get("on-policy", files.get("policy"))
  if "off-policy" in files:
    return "vision_multi_policy", [*result, "--on-policy-onnx", str(primary), "--off-policy-onnx", str(files["off-policy"])]
  return "vision_policy", [*result, "--policy-onnx", str(primary)]


def sha256_file(path: Path) -> str:
  digest = hashlib.sha256()
  with path.open("rb") as source:
    for block in iter(lambda: source.read(1024 * 1024), b""):
      digest.update(block)
  return digest.hexdigest()


def compile_env(gpu: bool = False) -> dict[str, str]:
  env = dict(os.environ)
  env["PYTHONPATH"] = os.pathsep.join((str(REPO_ROOT), str(REPO_ROOT / "tinygrad_repo"), env.get("PYTHONPATH", "")))
  defaults = {"DEV": "QCOM", "IMAGE": "1", "FLOAT16": "1", "NOLOCALS": "1", "JIT_BATCH_SIZE": "0", "OPENPILOT_HACKS": "1"}
  for key, value in defaults.items():
    env.setdefault(key, value)
  if gpu:
    for key in ("IMAGE", "NOLOCALS"):
      env.pop(key, None)
    # Personal branch: comma's Chestnut recipe (tinygrad examples/openpilot/helpers.py): FLOAT16 off, OPENPILOT_HACKS on.
    # The small-model flags (FLOAT16=1, no OPENPILOT_HACKS) NaN'd our big models on the road (2026-10-12).
    env.update(DEV="USB+AMD:LLVM", WARP_DEV="QCOM", GMMU="0", TC_OPT="2", TC_MIN_GLOBALS="32", FLOAT16="0", OPENPILOT_HACKS="1")
  return env


def parse_args(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--model", help="Stable output model ID")
  parser.add_argument("--version", required=True, choices=tuple(f"v{value}" for value in range(8, 17)))
  parser.add_argument("--input-dir", type=Path, default=Path("/data/openpilot/uncompiledmodels"))
  parser.add_argument("--output-dir", type=Path, default=Path("/data/openpilot/compiledmodels"))
  parser.add_argument("--input-format", choices=("auto", "supercombo", "split"), default="auto")
  parser.add_argument("--gpu", action="store_true")
  parser.add_argument("--image-history-pipeline", choices=("policy", "warp"), default="policy")
  parser.add_argument("--frame-skip", type=int)
  # personal branch
  parser.add_argument("--model-size", default="512x256", help="Model image size, e.g. 768x448 for the wide-FOV students")
  parser.add_argument("--name", help="Display name for --install")
  parser.add_argument("--install", action="store_true",
                      help="Install into the models root and list it in its catalog.json (personal branch local catalog)")
  args, unknown = parser.parse_known_args(argv)
  if unknown:
    if len(unknown) != 1 or not unknown[0].startswith("--") or args.model:
      parser.error("Use --model ID or one --ID flag")
    args.model = unknown[0][2:]
  if not args.model or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.model):
    parser.error("A lowercase model ID containing letters, digits, hyphens or underscores is required")
  if args.frame_skip is not None and args.frame_skip < 1:
    parser.error("--frame-skip must be positive")
  return args


def main(argv=None):
  args = parse_args(argv)
  model_type, source_args = driving_compile_args(source_files(args.input_dir, args.model), args.input_format)
  sources = [Path(source_args[index]) for index in range(1, len(source_args), 2)]
  for source in sources:
    with source.open("rb") as file:
      prefix = file.read(128)
    if not prefix or prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
      raise ValueError(f"Expected ONNX model bytes, not an empty file or Git LFS pointer: {source}")
  before = {path.name: sha256_file(path) for path in sources}
  output_dir = args.output_dir.resolve()
  output_dir.mkdir(parents=True, exist_ok=True)
  output = output_dir / f"{args.model}_driving_tinygrad.pkl"
  env = compile_env(args.gpu)
  with tempfile.TemporaryDirectory(prefix=f".{args.model}-compile-", dir=output_dir) as temporary:
    env["TMPDIR"] = temporary
    staged = Path(temporary) / output.name
    command = [sys.executable, "-m", "openpilot.starpilot.models.compile", "--model-type", model_type,
               "--model-size", args.model_size, "--camera-resolutions", "1928x1208", "1344x760",
               "--behavior-version", args.version, "--output", str(staged), "--out-of-band",
               "--image-history-pipeline", args.image_history_pipeline, *source_args]
    if args.frame_skip is not None:
      command += ["--frame-skip", str(args.frame_skip)]
    subprocess.run(command, cwd=REPO_ROOT, env=env, check=True)
    if {path.name: sha256_file(path) for path in sources} != before:
      raise ValueError("ONNX source changed during compilation")
    revision = next(item["commit"] for item in json.loads((REPO_ROOT / "upstream-sync.json").read_text())["dependencies"]
                    if item["path"] == "tinygrad_repo")
    receipt = {"model_id": args.model, "behavior_version": args.version, "model_type": model_type,
               "artifact_abi": "tinygrad_single_v1_arena", "compiler_revision": revision,
               "source_sha256": before, "artifact_sha256": sha256_file(staged), "artifact_size": staged.stat().st_size,
               "execution_device": env["DEV"], "warp_device": env.get("WARP_DEV", env["DEV"]),
               "image_history_pipeline": args.image_history_pipeline, "camera_resolutions": [[1928, 1208], [1344, 760]]}
    staged.replace(output)
    receipt_path = output.with_suffix(".build.json")
    temporary_receipt = Path(temporary) / receipt_path.name
    temporary_receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    temporary_receipt.replace(receipt_path)
  print(f"Compiled {output}; build receipt {receipt_path}")
  if args.install:
    print(f"Installed {install(output, receipt, args.name or args.model, args.gpu)}")
  return 0


def install(artifact: Path, receipt: dict, name: str, gpu: bool, root: Path | None = None) -> Path:
  """Personal branch: copy the artifact to where the catalog runtime reads it and list it in root/catalog.json, the
  file the manager reads for installable models (validated against this tinygrad, so StarPilot never overwrites it)."""
  import shutil
  if str(REPO_ROOT) not in sys.path:  # run as scripts/model_compiler.py, only the compile subprocess got PYTHONPATH
    sys.path.insert(0, str(REPO_ROOT))
  from openpilot.starpilot.models.catalog import ARTIFACT_ABI, COMPILER_REVISION, GENERATION
  from openpilot.starpilot.models.manager import ROOT, atomic_json, read_json, state_lock, validate_manifest
  root = ROOT if root is None else root
  if receipt["compiler_revision"] != COMPILER_REVISION:
    raise ValueError(f"artifact compiled for {receipt['compiler_revision']}, runtime is {COMPILER_REVISION}")
  model_id = receipt["model_id"]
  target = root / model_id / f"{model_id}_driving_tinygrad.pkl"
  with state_lock(root):
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f".{target.name}.tmp")
    shutil.copyfile(artifact, staged)
    staged.replace(target)
    try:
      document = read_json(root / "catalog.json")
      validate_manifest(document)
    except (OSError, ValueError, TypeError):
      document = {"generation": GENERATION, "compiler_revision": COMPILER_REVISION, "artifact_abi": ARTIFACT_ABI, "models": []}
    row = {"id": model_id, "name": name, "version": receipt["behavior_version"], "uses_external_gpu": gpu, "series": "Local",
           "artifact_format": ARTIFACT_ABI, "artifact_sha256": receipt["artifact_sha256"], "artifact_size": receipt["artifact_size"],
           "artifact_chunk_count": 0}
    document["models"] = [entry for entry in document["models"] if entry.get("id") != model_id] + [row]
    validate_manifest(document)
    atomic_json(root / "catalog.json", document)
  return target


if __name__ == "__main__":
  raise SystemExit(main())
