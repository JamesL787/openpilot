# StarPilot Model Rebuild

This is the supported workflow for changing the vendored tinygrad revision and
releasing a new model manifest generation. A manifest generation represents one
tinygrad ABI. Model behavior versions (`v8` through `v16`) are independent and
must remain unchanged when only tinygrad changes.

The published generation is **v25**, whose legacy artifacts were built with
tinygrad `e837e367aac9e1a66e689f4f32ce20ca9367df13`. VFN's next-generation
runtime is pinned to `f6fc4e3f2c3db5fae1e19cbfbc3ad9fc579a12ae` so it can build
comma's fused Chestnut model graph. New external-GPU artifacts use format v2
and record that exact compiler revision; modeld refuses a v2 artifact when its
pin differs from the runtime.

Legacy format-v1 artifacts remain loadable during the transition so the whole
catalog does not have to be rebuilt at once. This is a compatibility allowance,
not proof that every old artifact is safe: validate each selected v1 artifact
on the comma after a tinygrad bump. The built-in RDF43 artifact must always pass
a real QCOM warmup before deployment. The next published catalog generation
must use a new manifest version and must not mix old and new compiler pins.

The current development comma is `comma@192.168.1.118`.

## Release Contract

- Keep every existing StarPilot model ID stable across manifest generations.
- Store HF artifacts under `models/v25/<model-id>/`.
- Store GitHub fallback artifacts on the `Models` branch under `v25/<model-id>/`.
- Name every logical artifact `<model-id>_driving_tinygrad.pkl`.
- Publish native chunks as `.chunkNNofNN` plus `.chunkmanifest`.
- Serialize every v25 driving artifact out-of-band; this applies to normal QCOM
  models as well as external-GPU models.
- Include `artifact_sha256` and `artifact_chunk_count` in the manifest.
- Set `uses_external_gpu: true` only for models compiled for Chestnut.
- Do not rename an artifact from another tinygrad revision. Published PKLs must
  use the exact pin declared for their manifest generation.
- Do not add models absent from the existing StarPilot catalog unless the
  release explicitly requests them.

The downloader checks Hugging Face first and GitHub second. There is no GitLab
fallback. The HF manifest lives only at `manifests/model_names_v25.json`, old
artifacts live under `models/v24/`, and current artifacts live under
`models/v25/`. The v25 downloader never probes unversioned or v24 artifact
paths; missing v25 artifacts fail safely instead of loading an incompatible
pickle.

## Tinygrad Bump

1. Record the exact tinygrad commit used by the compatible source catalog.
2. Replace `tinygrad_repo/` from that commit, excluding nested Git metadata.
3. Write the full SHA to `tinygrad_repo/TINYGRAD_COMMIT`.
4. Review upstream `modeld`, compiler, parser, and camera-warp changes. Merge
   required ABI changes into StarPilot's existing multi-model runtime; never
   replace StarPilot `modeld.py` wholesale.
5. Before publishing rebuilt artifacts, increment `MANIFEST_CANDIDATES` to a
   new single version. Do not put f6fc artifacts into the published v25 catalog.
6. Sync the exact tree to the compiler before building anything:

```bash
./dev sync
rsync -az --delete --exclude=.git --exclude=__pycache__ -e ssh \
  tinygrad_repo/ comma@192.168.1.118:/data/openpilot/tinygrad_repo/
rsync -az -e ssh selfdrive/modeld/ \
  comma@192.168.1.118:/data/openpilot/selfdrive/modeld/
rsync -az -e ssh scripts/model_compiler.py \
  comma@192.168.1.118:/data/openpilot/scripts/model_compiler.py
rsync -az -e ssh models comma@192.168.1.118:/data/openpilot/models
```

Confirm the device marker before compiling:

```bash
ssh comma@192.168.1.118 \
  'cat /data/openpilot/tinygrad_repo/TINYGRAD_COMMIT'
```

Before changing `/data/openpilot`, a legacy QCOM artifact can be smoke-tested
against the new tinygrad from `/data/tmp`. Run from outside `/data/openpilot` so
Python does not import the checkout's old `tinygrad` through `sys.path[0]`:

```bash
rsync -az --delete --exclude=__pycache__ tinygrad_repo/ \
  comma@192.168.1.118:/data/tmp/vfn-tinygrad-f6fc-test/

ssh comma@192.168.1.118 '
  cd /data/openpilot && source ./launch_env.sh
  cd /data/tmp
  DEV=QCOM WARP_DEV=QCOM \
  PYTHONPATH=/data/tmp/vfn-tinygrad-f6fc-test:/data/openpilot \
  timeout 120 python3 -c '\''from openpilot.selfdrive.modeld.modeld import ModelState; m=ModelState(1928, 1208, model_id_override="rdf43", write_model_version=False); m.warmup(); print("RDF43 warmup passed")'\''
'
```

## Reuse Compatible Artifacts

Reusing an artifact is preferred when its catalog records the exact same
tinygrad SHA and exact same source-model commit. Display names and release dates
are not sufficient proof. Copy compatible chunks server-side so the Mac never
stores a second multi-gigabyte artifact, but rename every destination chunk to
the stable StarPilot model ID.

Example:

```bash
hf buckets cp \
  'hf://datasets/<source>/<path>/<source-file>.chunk01of02' \
  'hf://buckets/StarPilot-Driving/StarPilot-Resources/models/v25/pop223/pop223_driving_tinygrad.pkl.chunk01of02'
```

Write `2` to `pop223_driving_tinygrad.pkl.chunkmanifest`, upload it last, and
put the source artifact's full SHA-256 and chunk count into the v25 manifest.
Upload the manifest only after every listed artifact directory is complete.

## Compile Missing Models

Archived sources live under:

```text
hf://buckets/StarPilot-Driving/StarPilot-Resources/onnx/<source-id>/
```

Stage one model at a time in `/data/openpilot/uncompiledmodels`; this avoids
filling the comma and prevents `./models` from selecting stale input files.

```bash
./models --model <model-id> --version <behavior-version>
./models --model <gpu-model-id> --version v16 --gpu
```

`--gpu` now always builds the fused comma graph with the required Chestnut
environment: `DEV=USB+AMD:LLVM`, `FRAME_DEV=CPU`, `FLOAT16=1`, `TC_OPT=2`, and
`TC_MIN_GLOBALS=32`. The compiler captures warp plus policy in one TinyJit and
runs 20 deterministic replay checks per seed after the pickle round trip. Set
`STARPILOT_GPU_VALIDATION_RUNS` only when intentionally changing that count.

For a local TGC candidate, build without replacing the installed model first:

```bash
cd /data/openpilot
source ./launch_env.sh
./models \
  --model local-tgc \
  --input-dir /data/openpilot/uncompiledmodels/tgc \
  --output-dir /data/openpilot/compiledmodels/f6fc-candidate \
  --input-format supercombo \
  --version v16 \
  --image-history-pipeline policy \
  --gpu \
  --no-install

python3 scripts/validate_model_artifact.py \
  --artifact /data/openpilot/compiledmodels/f6fc-candidate/local-tgc_driving_tinygrad.pkl \
  --model local-tgc --version v16 --external-gpu
```

Only after validation should the candidate be copied atomically into
`/data/models/local-tgc_driving_tinygrad.pkl`. Keep RDF43 selected for the first
offroad modeld soak; select TGC only after repeated outputs remain finite and
bounded. A v2 artifact with the wrong tinygrad pin fails at load instead of
silently running.

The default input is a single supercombo ONNX. For legacy sources use:

```bash
./models --<model-id> --input-format split --version <behavior-version>
```

Every non-local release build emits an OOB artifact as native chunks and removes
the temporary full PKL. `./models --local-<id>` intentionally keeps one OOB PKL
for local use.

The resumable bulk helper is:

```bash
STAR_PILOT_MODEL_REMOTE=comma@192.168.1.118 \
python3 scripts/model_rebuild_pipeline.py compile \
  --workspace /Volumes/T5/StarPilot-Model-Rebuild \
  --source-map scripts/model_source_map_v25.json \
  --base-manifest ~/StarPilot-Resources/model_names_v25.json
```

Failures are recorded under `results/`; rerun the same command to resume.

## Driver Monitoring And Default

Driver monitoring is built once per tinygrad generation:

```bash
./models --dm \
  --input-dir /data/openpilot/uncompiledmodels \
  --output-dir /tmp/dm_artifacts
```

Replace these four files together:

- `dmonitoring_model_tinygrad.pkl`
- `dmonitoring_model_metadata.pkl`
- `dm_warp_1928x1208_tinygrad.pkl`
- `dm_warp_1344x760_tinygrad.pkl`

Recompile RDF V4 with the same pin and replace the built-in
`selfdrive/modeld/models/driving_tinygrad.pkl` native chunk set. Never commit a
full built-in PKL over the repository limit.

## Validation

Run repository tests first:

```bash
./dev sync
./.venv/bin/pytest -q -n0 \
  starpilot/assets/tests/test_model_pipeline.py \
  common/tests/test_file_chunker.py \
  scripts/tests/test_model_release.py
```

For representative v8, v11, v12, v15, v16, and GPU artifacts, validate both
camera resolutions on real QCOM and require finite plan, lane-line, road-edge,
lead, pose, and action outputs. Then start `modeld` and confirm stable
`modelV2` publication. Validate DM `driverStateV2` at both resolutions.

## Device Migration

When `ModelManifestVersion` changes, the model manager retains the selected
model ID but deletes every non-local downloaded driving artifact from the old
generation, including full PKLs, `.pNN` parts, native chunks, and chunk
manifests. It then downloads that ID's v25 chunks. Local models and DM files are
not deleted. If the selected v25 artifact cannot be downloaded and verified,
the manager selects the built-in RDF V4 model.

Test this explicitly before release by starting with a v24 selected model and
checking that no v24 driving artifact remains under `/data/models` after the
v25 manifest is applied.
