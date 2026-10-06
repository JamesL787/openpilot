# NovaSpark local model package

This directory is the repository copy of the package supplied for
`ns-bosch-radar-testing`. The original 126 MB artifact is split into three chunks so every
tracked file remains below the repository file-size limit. Reassemble it in this directory
with:

```bash
python3 - <<'PY'
from pathlib import Path

root = Path("model_artifacts/novaspark-ns-bosch-radar-testing")
parts = sorted(root.glob("local-novaspark_driving_tinygrad.pkl.chunk[0-9][0-9]of[0-9][0-9]"))
output = root / "local-novaspark_driving_tinygrad.pkl"
with output.open("wb") as destination:
  for part in parts:
    destination.write(part.read_bytes())
PY
```

Verify the assembled artifact with `sha256sum -c local-novaspark_driving_tinygrad.pkl.sha256`.
The assembled `.pkl` is ignored by git and can be removed after installation.

The supplied `SHA256SUMS` claimed `abe5c5e...` for `local-novaspark.json`, but the supplied
file hashes to `b6e77b8...` both before and after CR stripping. The repository checksum list
records the file actually supplied. Its embedded artifact checksum matches both the supplied
model and the generated `.sha256` file.
