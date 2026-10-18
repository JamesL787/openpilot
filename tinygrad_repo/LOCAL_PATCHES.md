# Local patches (StarPilot / Night Star personal branch)

Vendored tinygrad is upstream `02e698160eed1751738212144a7ea2cfb160b3f1` (comma's pin since commaai/openpilot#39085,
2026-10-14) without `AGENTS.md`, plus these patches carried from StarPilot 7.0's vendored `9d0446a4`:

- `tinygrad/helpers.py::fetch_fw` reads installed `.zst` firmware through the `zstandard` streaming decoder on Python
  before 3.14. AGNOS 19.6.20's `amdgpu/psp_14_0_2_sos.bin.zst` has no frame content-size field, so the one-shot decoder
  raised before Tinygrad could compare the decompressed bytes with its pinned firmware SHA-256. Streaming keeps the same
  hash check and the pinned upstream fallback. Test: `test/null/test_helpers.py::TestFirmwareFetch`.
- `tinygrad/runtime/support/am/startup_trace.py` (new) and its hooks in `am/amdev.py`, `am/ip.py` and `support/usb.py`:
  opt-in (`STARPILOT_GPU_STARTUP_TRACE=1`) Chestnut boot tracing used by StarPilot's modeld. On 02e698160e the trace
  notes wrap upstream's new quiesce-before-mode1-reset sequence.
- `examples/openpilot/helpers.py`: `load_pickle` accepts an out-of-band artifact with no buffers, and `benchmark` selects
  its Context when called instead of probing `Device.DEFAULT` on import.

Dropped from 7.0's set: the `ops_qcom.py` program-cache key fix (02e698160e removed that cache).
