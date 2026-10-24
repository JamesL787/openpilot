# Night Star → StarPilot 7.0 port ledger

> **Closed 2026-10-18 (slice 10).** This is a one-time snapshot of the 6.x → 7.0 differences, kept for reference. The live record of everything after it (SGSP syncs, ns-bosch lateral syncs, ports from other people, decisions and reverts) is the port README (`docs/night_star_port/README.md`: base-history table and decisions log). Files added to ns-bosch or ported from others after the snapshot are not listed here.
Generated 2026-10-16 from `git diff 249b03a3f5..{origin/vfn, origin/ns-bosch-radar-testing}` (249b03a3f5 = our last StarPilot 6.x merge base), mapped onto `starpilot/SecretGoodStarPilot` @ `89430a70da`. Each row is one file we changed. Status column is the work tracker: `todo` → `wip` → `done` / `dropped` (say why).

Decisions: **PORT** = carry the change onto the 7.0 file; **RE-HOME** = the 6.x file is gone, the logic moves into a 7.0 owner module; **REWRITE** = 7.0 replaced the subsystem, re-implement ours in its design; **DROP** = 7.0 already covers it; **REBUILD** = binary, regenerate via Docker; **COPY** = standalone, copy as is; **REVIEW** = undecided.

## By area

| Area | Files | Our + lines | Default decision |
|---|---:|---:|---|
| vendored: tinygrad | 630 | 46105 | DROP - take 7.0 tinygrad pin, rebuild models |
| jetlink | 72 | 15639 | DROP - 7.0 ships native Jetlink |
| lateral controller | 13 | 4660 | PORT - plug into lateral_controller_factory |
| modeld / models | 36 | 3598 | REVIEW each vs 7.0 comma-master modeld |
| tools | 35 | 3325 | COPY - standalone tools |
| Honda car layer | 12 | 2286 | PORT onto 7.0 refactored Honda |
| longitudinal | 15 | 1569 | RE-HOME into openpilot/starpilot/longitudinal |
| built artifact | 87 | 1368 | REBUILD; REBUILD - Docker, never copy |
| vendored: third_party | 10 | 1310 | REVIEW - likely take 7.0 |
| UI | 29 | 950 | REWRITE in 7.0 openpilot/starpilot/ui |
| long: Bosch-A radar | 4 | 831 | RE-HOME into 7.0 bosch_a_radar.py |
| Galaxy | 7 | 707 | REWRITE against 7.0 galaxy |
| other | 27 | 705 | REVIEW |
| build / scripts | 8 | 582 | REVIEW |
| controls core | 6 | 488 | PORT hooks into rewritten controlsd |
| docs | 4 | 461 | COPY ours |
| system / manager | 7 | 394 | PORT selectively |
| params / schema | 4 | 141 | PORT keys into 7.0 contracts; rebuild |
| DBC | 17 | 81 | REVIEW - regenerate from 7.0 sources |
| StarPilot glue | 5 | 81 | RE-HOME into 7.0 feature owners |
| panda safety | 2 | 27 | PORT - safety critical (Nidec hybrid brake) |
| opendbc other | 1 | 11 | REVIEW |

## Files

### vendored: tinygrad (630 files) — DROP - take 7.0 tinygrad pin, rebuild models

Collapsed; see `git diff 249b03a3f5 <branch> --stat`.

### jetlink (72 files) — DROP - 7.0 ships native Jetlink

Collapsed; see `git diff 249b03a3f5 <branch> --stat`.

### lateral controller

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `starpilot/assets/nnff_models/HONDA_CLARITY.json` | bosch+vfn | 1824 | mod | **gone** | PORT - plug into lateral_controller_factory | dropped: NNFF not ported (7.0 removed it) |
| `selfdrive/controls/lib/honda_eps_firmware_ff.py` | bosch+vfn | 810 | new | **gone** | PORT - plug into lateral_controller_factory | done (slice 1; synced to ns-bosch @ 9d8de58075 on 10-17; Insight default_on) |
| `selfdrive/controls/tests/test_honda_eps_firmware_ff.py` | bosch+vfn | 733 | new | **gone** | PORT - plug into lateral_controller_factory | done (slices 1-3) |
| `selfdrive/controls/lib/latcontrol_pid.py` | bosch+vfn | 333 | mod | `openpilot/selfdrive/controls/lib/latcontrol_pid.py` | PORT - plug into lateral_controller_factory | done (slice 3: ported as latcontrol_honda_modified_pid.py; 7.0 file untouched) |
| `selfdrive/controls/lib/latcontrol_honda_eps.py` | bosch+vfn | 239 | new | **gone** | PORT - plug into lateral_controller_factory | done (slice 2) |
| `selfdrive/controls/lib/tests/test_latcontrol_pid_eps_modified.py` | bosch+vfn | 224 | new | **gone** | PORT - plug into lateral_controller_factory | done (slice 3; moved to selfdrive/controls/tests/) |
| `selfdrive/controls/lib/honda_lateral_common.py` | bosch+vfn | 191 | new | **gone** | PORT - plug into lateral_controller_factory | done (slice 1; SR curves kept as data only, not used by controllers) |
| `selfdrive/controls/tests/test_latcontrol_pid_override_fade.py` | bosch+vfn | 99 | new | **gone** | PORT - plug into lateral_controller_factory | done (slice 3) |
| `selfdrive/controls/lib/honda_eps_rack_map.py` | bosch+vfn | 92 | new | **gone** | PORT - plug into lateral_controller_factory | done (slice 1) |
| `system/manager/test/test_honda_eps_param_migration.py` | bosch+vfn | 52 | new | **gone** | PORT - plug into lateral_controller_factory | done: test_honda_eps_settings (slice 5) |
| `selfdrive/controls/tests/test_latcontrol_pid_clarity_symmetry.py` | bosch+vfn | 45 | new | **gone** | PORT - plug into lateral_controller_factory | done (slice 3) |
| `starpilot/controls/lib/neural_network_feedforward.py` | bosch+vfn | 17 | mod | **gone** | PORT - plug into lateral_controller_factory | dropped: NNFF not ported (7.0 removed it) |
| `selfdrive/controls/tests/test_latcontrol.py` | bosch+vfn | 1 | mod | `openpilot/selfdrive/controls/tests/test_latcontrol.py` | PORT - plug into lateral_controller_factory | done: slices 2-3 (controller factory) |

### modeld / models

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `selfdrive/modeld/modeld.py` | bosch+vfn | 825 | mod | `openpilot/selfdrive/modeld/modeld.py` | REVIEW each vs 7.0 comma-master modeld | done: #39091 seed + reprojection source; rest left to 7.0/comma |
| `selfdrive/modeld/tests/test_usbgpu_helpers.py` | bosch+vfn | 401 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | held: Chestnut extras after a 7.0 eGPU drive |
| `selfdrive/modeld/compile_modeld.py` | bosch+vfn | 344 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/tests/test_reproject_daemons.py` | vfn | 314 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/reprojectcalibd.py` | vfn | 215 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/tests/test_stateful_model_artifacts.py` | bosch | 203 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/reprojectd.py` | vfn | 181 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/reproject_c4/geometry.py` | vfn | 148 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/reproject_c4/fit.py` | vfn | 112 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/reproject_c4/meter.py` | vfn | 111 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/reproject_c4/tables.py` | vfn | 99 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `scripts/model_compiler.py` | bosch+vfn | 86 | mod | `scripts/model_compiler.py` | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/reproject_c4/kernel.py` | vfn | 86 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/SConscript` | vfn | 80 | mod | `openpilot/selfdrive/modeld/SConscript` | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/tests/test_model_fallback.py` | vfn | 68 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | held: Chestnut extras after a 7.0 eGPU drive |
| `selfdrive/modeld/helpers.py` | vfn | 59 | mod | `openpilot/selfdrive/modeld/helpers.py` | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/reproject_c4/rotation.py` | vfn | 52 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/reproject_config.py` | vfn | 51 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `starpilot/assets/model_manager.py` | bosch+vfn | 41 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `scripts/validate_model_artifact.py` | bosch+vfn | 39 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/reproject_c4/cameras.py` | vfn | 28 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/dmonitoringmodeld.py` | vfn | 21 | mod | `openpilot/selfdrive/modeld/dmonitoringmodeld.py` | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/reproject_c4/__init__.py` | vfn | 12 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/modeld/tests/test_model_laboratory.py` | bosch+vfn | 8 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `scripts/model_rebuild_pipeline.py` | vfn | 5 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/get_model_metadata.py` | vfn | 4 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `starpilot/system/the_galaxy/assets/components/tools/model_manager.js` | bosch | 3 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/driving_tinygrad.pkl.chunkmanifest` | vfn | 1 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/driving_tinygrad.pkl.sha256` | vfn | 1 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/dmonitoring_model.onnx` | vfn | 0 | mod | `openpilot/selfdrive/modeld/models/dmonitoring_model.onnx` | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/driving_supercombo.onnx` | vfn | 0 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/driving_tinygrad.pkl.chunk01of02` | vfn | 0 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/driving_tinygrad.pkl.chunk01of03` | vfn | 0 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/driving_tinygrad.pkl.chunk02of02` | vfn | 0 | new | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/driving_tinygrad.pkl.chunk02of03` | vfn | 0 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |
| `selfdrive/modeld/models/driving_tinygrad.pkl.chunk03of03` | vfn | 0 | mod | **gone** | REVIEW each vs 7.0 comma-master modeld | dropped: 7.0's model pipeline |

### tools

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `eps_tools/flash.py` | bosch+vfn | 535 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `tune_report.py` | bosch+vfn | 463 | new | **gone** | COPY - standalone tools | dropped: you dropped the tune report |
| `eps_tools/eps-diag.py` | bosch+vfn | 347 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `tools/lateral/eps_report.py` | bosch+vfn | 318 | new | `openpilot/tools/lateral/eps_report.py` | COPY - standalone tools | done: 7.0 message names |
| `eps_tools/eps-update.py` | bosch+vfn | 315 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `tools/lateral/fit_rack_map.py` | bosch+vfn | 221 | new | `openpilot/tools/lateral/fit_rack_map.py` | COPY - standalone tools | done: 7.0 message names |
| `tools/lateral/fit_column_load.py` | bosch+vfn | 146 | new | `openpilot/tools/lateral/fit_column_load.py` | COPY - standalone tools | done: 7.0 message names |
| `tools/lateral/plan_timing.py` | bosch+vfn | 141 | new | `openpilot/tools/lateral/plan_timing.py` | COPY - standalone tools | done: 7.0 message names |
| `tools/replay/lib/radar_debug.py` | bosch+vfn | 114 | new | **gone** | COPY - standalone tools | done: replay radar roles on 7.0's raylib UI |
| `tools/lateral/fit_yaw_scale.py` | bosch+vfn | 113 | new | `openpilot/tools/lateral/fit_yaw_scale.py` | COPY - standalone tools | done: 7.0 message names |
| `eps_tools/check_rwd.py` | bosch+vfn | 104 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `eps_tools/README.md` | bosch+vfn | 91 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `eps_tools/rwd_format/x31.py` | bosch+vfn | 91 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `tools/lateral/live_row_fit.py` | bosch+vfn | 74 | new | `openpilot/tools/lateral/live_row_fit.py` | COPY - standalone tools | done: 7.0 message names |
| `eps_tools/rwd/README.md` | bosch+vfn | 73 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `eps_tools/rwd_format/base.py` | bosch+vfn | 60 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `eps_tools/rwd_format/x5a.py` | bosch+vfn | 60 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `eps_tools/rwd_format/header.py` | bosch+vfn | 35 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `eps_tools/rwd_format/header_value.py` | bosch+vfn | 24 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |
| `eps_tools/rwd/39990-TBA,C020-20260805-ClarityPminus5-P117to265-D737-KFF45-Norm1650-Trk4500-TargetMapD-Telem-SpeedClamp0-Pclamp7373.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/39990-TBA-C120-linear-max.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/39990-TBA-C120-stock.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/39990-TLA-A040-linear-max.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/39990-TLA-A040-stock.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/39990-TLA-A040_tq30000_a9000_44256c0b.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/39990-TRW-A020-06.18.2026-stable.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/39990-TXM-A040-linear-max.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/39990-TXM-A040-stock.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/Clarity-1663.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/ClarityMax-20260719-1202-FFV1.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/ClarityMax-20260719-1202-Smooth.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/ClarityMax-20260722-1806-FF45-Tracker3200-Norm1650-3840.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/Clarity_PShapeSmooth_KFF45_R6Lead_R6L2_B6_NoSHLL2_CCP728_Telem6A3_TXFIX.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd/Clarity_R6L2_B6_FFV1P_KFF8_NoSHLL2_CCP728_Telem6A3_TXFIX.rwd` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | kept out of the repo (eps_tools/rwd/README.md); your call |
| `eps_tools/rwd_format/__init__.py` | bosch+vfn | 0 | new | **gone** | COPY - standalone tools | done: copied, slice 10 (no firmware images) |

### Honda car layer

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `opendbc_repo/opendbc/car/honda/carcontroller.py` | bosch+vfn | 586 | mod | `opendbc_repo/opendbc/car/honda/carcontroller.py` | PORT onto 7.0 refactored Honda | wip (slices 4+6 lateral done; long side is slice 8) |
| `opendbc_repo/opendbc/car/honda/tests/test_carcontroller_learners.py` | bosch+vfn | 526 | new | **gone** | PORT onto 7.0 refactored Honda | dropped: planner-level, left to StarPilot 7.0 |
| `opendbc_repo/opendbc/car/honda/tests/test_honda.py` | bosch+vfn | 327 | mod | `opendbc_repo/opendbc/car/honda/tests/test_honda.py` | PORT onto 7.0 refactored Honda | done: split into the ported test files (slices 4-6, 8) |
| `opendbc_repo/opendbc/car/honda/steer_ratio.py` | bosch+vfn | 292 | new | **gone** | PORT onto 7.0 refactored Honda | done (slice 1) |
| `opendbc_repo/opendbc/car/honda/tests/test_bosch_a_radar.py` | bosch+vfn | 194 | mod | `opendbc_repo/opendbc/car/honda/tests/test_bosch_a_radar.py` | PORT onto 7.0 refactored Honda | done: Trung's decoder in bosch_a_radar.py (DBC kept as 7.0) |
| `opendbc_repo/opendbc/car/honda/interface.py` | bosch+vfn | 139 | mod | `opendbc_repo/opendbc/car/honda/interface.py` | PORT onto 7.0 refactored Honda | wip (slice 2 lateral done; Bosch-A radar default, vEgoStopping, Nidec hybrid safety still todo) |
| `opendbc_repo/opendbc/car/honda/yaw_rate.py` | bosch+vfn | 87 | new | **gone** | PORT onto 7.0 refactored Honda | done (slice 6) |
| `opendbc_repo/opendbc/car/honda/tests/test_steer_ratio.py` | bosch+vfn | 74 | new | **gone** | PORT onto 7.0 refactored Honda | done (slice 1) |
| `opendbc_repo/opendbc/car/honda/carstate.py` | bosch+vfn | 29 | mod | `opendbc_repo/opendbc/car/honda/carstate.py` | PORT onto 7.0 refactored Honda | wip (slices 4+6 done; long side slice 8) |
| `opendbc_repo/opendbc/car/honda/hondacan.py` | bosch+vfn | 16 | mod | `opendbc_repo/opendbc/car/honda/hondacan.py` | PORT onto 7.0 refactored Honda | wip (slice 4 hybrid brake done; create_acc_commands brake bit todo, slice 8) |
| `opendbc_repo/opendbc/car/honda/values.py` | bosch+vfn | 14 | mod | `opendbc_repo/opendbc/car/honda/values.py` | PORT onto 7.0 refactored Honda | wip (VGR flags done; safety flags: see README) |
| `opendbc_repo/opendbc/car/honda/fingerprints.py` | bosch+vfn | 2 | mod | `opendbc_repo/opendbc/car/honda/fingerprints.py` | PORT onto 7.0 refactored Honda | done (slice 2) |

### longitudinal

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `selfdrive/controls/lib/blotv2.py` | bosch+vfn | 247 | new | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `selfdrive/controls/lib/longcontrol.py` | bosch+vfn | 191 | mod | `openpilot/selfdrive/controls/lib/longcontrol.py` | RE-HOME into openpilot/starpilot/longitudinal | held: Clarity stopping shape, after a 7.0 test drive |
| `selfdrive/controls/lib/longitudinal_planner.py` | bosch+vfn | 174 | mod | `openpilot/selfdrive/controls/lib/longitudinal_planner.py` | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `selfdrive/controls/lib/tests/test_blotv2.py` | bosch+vfn | 171 | new | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `selfdrive/controls/lib/nrdr_long_tune.py` | bosch+vfn | 167 | new | **gone** | RE-HOME into openpilot/starpilot/longitudinal | held: Clarity stopping shape, after a 7.0 test drive |
| `selfdrive/controls/tests/test_longitudinal_planner.py` | bosch+vfn | 143 | mod | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `selfdrive/controls/lib/longitudinal_lead.py` | bosch+vfn | 97 | new | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `selfdrive/controls/tests/test_curve_speed_controller.py` | bosch+vfn | 82 | mod | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `selfdrive/controls/tests/test_longcontrol.py` | bosch+vfn | 78 | mod | `openpilot/selfdrive/controls/tests/test_longcontrol.py` | RE-HOME into openpilot/starpilot/longitudinal | held: Clarity stopping shape, after a 7.0 test drive |
| `selfdrive/controls/tests/test_starpilot_vcruise.py` | bosch+vfn | 67 | mod | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `selfdrive/ui/layouts/settings/starpilot/longitudinal.py` | bosch+vfn | 52 | mod | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `starpilot/controls/lib/curve_speed_controller.py` | bosch+vfn | 48 | mod | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py` | bosch+vfn | 26 | mod | `openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py` | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `starpilot/controls/lib/starpilot_vcruise.py` | bosch+vfn | 21 | mod | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |
| `starpilot/controls/starpilot_planner.py` | bosch+vfn | 5 | mod | **gone** | RE-HOME into openpilot/starpilot/longitudinal | dropped: planner-level, left to StarPilot 7.0 |

### built artifact (87 files) — REBUILD - Docker, never copy

Collapsed; see `git diff 249b03a3f5 <branch> --stat`.

### vendored: third_party (10 files) — REVIEW - likely take 7.0

Collapsed; see `git diff 249b03a3f5 <branch> --stat`.

### UI

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `selfdrive/ui/layouts/settings/starpilot/nrdr_tuning.py` | bosch+vfn | 500 | new | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | done: Night Star page; tune report dropped |
| `selfdrive/assets/fonts/como-heavy.fnt` | bosch+vfn | 96 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/mici/tests/test_mici_device_reboot.py` | bosch+vfn | 55 | new | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/widgets/exp_mode_button.py` | bosch+vfn | 55 | mod | `openpilot/selfdrive/ui/widgets/exp_mode_button.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/onroad/augmented_road_view.py` | vfn | 37 | mod | `openpilot/selfdrive/ui/onroad/augmented_road_view.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/starpilot/lateral.py` | bosch+vfn | 36 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/settings.py` | bosch+vfn | 33 | mod | `openpilot/selfdrive/ui/layouts/settings/settings.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/lib/starpilot_version.py` | bosch+vfn | 25 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/mici/layouts/settings/device.py` | bosch+vfn | 19 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/ui_state.py` | bosch+vfn | 13 | mod | `openpilot/selfdrive/ui/ui_state.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/starpilot/aethergrid.py` | bosch+vfn | 11 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/lib/tests/test_starpilot_version.py` | bosch+vfn | 11 | new | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/soundd.py` | bosch+vfn | 11 | mod | `openpilot/selfdrive/ui/soundd.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/home.py` | bosch+vfn | 8 | mod | `openpilot/selfdrive/ui/layouts/home.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/starpilot/vehicle.py` | bosch+vfn | 6 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/mici/layouts/home.py` | bosch+vfn | 6 | mod | `openpilot/selfdrive/ui/mici/layouts/home.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/starpilot/main_panel.py` | bosch+vfn | 5 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/mici/layouts/settings/settings.py` | bosch | 5 | mod | `openpilot/selfdrive/ui/mici/layouts/settings/settings.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/starpilot/driving_model.py` | vfn | 4 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/starpilot/panel.py` | bosch+vfn | 4 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/mici/layouts/settings/developer.py` | bosch | 2 | mod | `openpilot/selfdrive/ui/mici/layouts/settings/developer.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/tests/test_starpilot_navigation_structure.py` | bosch | 2 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/assets/fonts/process.py` | bosch+vfn | 1 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/device.py` | vfn | 1 | mod | `openpilot/selfdrive/ui/layouts/settings/device.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/starpilot/system_settings.py` | bosch+vfn | 1 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/mici/widgets/pairing_dialog.py` | bosch+vfn | 1 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 7.0 provider system (Konik only on night-star7) |
| `system/ui/lib/application.py` | bosch+vfn | 1 | mod | `openpilot/system/ui/lib/application.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/ui/layouts/settings/developer.py` | bosch | 1 | mod | `openpilot/selfdrive/ui/layouts/settings/developer.py` | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |
| `selfdrive/assets/fonts/como-heavy.png` | bosch+vfn | 0 | mod | **gone** | REWRITE in 7.0 openpilot/starpilot/ui | dropped: 6.x UI, replaced by 7.0's UI and the Night Star page |

### long: Bosch-A radar

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `selfdrive/controls/tests/test_radard_bosch.py` | bosch+vfn | 445 | new | **gone** | RE-HOME into 7.0 bosch_a_radar.py | dropped: radard lead policy left to 7.0 |
| `opendbc_repo/opendbc/dbc/honda_bosch_a_radar.dbc` | bosch | 177 | mod | `opendbc_repo/opendbc/dbc/honda_bosch_a_radar.dbc` | RE-HOME into 7.0 bosch_a_radar.py | done: Trung's decoder in bosch_a_radar.py (DBC kept as 7.0) |
| `opendbc_repo/opendbc/car/honda/radar_interface.py` | bosch | 144 | mod | `opendbc_repo/opendbc/car/honda/radar_interface.py` | RE-HOME into 7.0 bosch_a_radar.py | done: Trung's decoder in bosch_a_radar.py (DBC kept as 7.0) |
| `selfdrive/controls/radard.py` | bosch | 65 | mod | `openpilot/selfdrive/controls/radard.py` | RE-HOME into 7.0 bosch_a_radar.py | done: Kalman dt only; lead policy left to 7.0 |

### Galaxy

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `starpilot/common/assets/device_settings_layout.json` | bosch+vfn | 483 | mod | **gone** | REWRITE against 7.0 galaxy | dropped: 6.x Galaxy, replaced by the Night Star page |
| `starpilot/system/the_galaxy/assets/mobile/js/components/JetlinkModelsCard.js` | bosch | 83 | new | **gone** | REWRITE against 7.0 galaxy | dropped: 7.0 ships Jetlink |
| `starpilot/system/the_galaxy/the_galaxy.py` | bosch+vfn | 68 | mod | **gone** | REWRITE against 7.0 galaxy | dropped: 6.x Galaxy, replaced by the Night Star page |
| `starpilot/system/the_galaxy/tests/test_device_settings_layout.py` | bosch+vfn | 50 | mod | **gone** | REWRITE against 7.0 galaxy | dropped: 6.x Galaxy, replaced by the Night Star page |
| `starpilot/system/the_galaxy/assets/components/tools/device_settings.js` | bosch+vfn | 12 | mod | **gone** | REWRITE against 7.0 galaxy | dropped: 6.x Galaxy, replaced by the Night Star page |
| `starpilot/system/the_galaxy/tests/test_navigation_params.py` | bosch+vfn | 7 | mod | **gone** | REWRITE against 7.0 galaxy | dropped: 6.x Galaxy, replaced by the Night Star page |
| `starpilot/system/the_galaxy/assets/mobile/js/views/ModelManager.js` | bosch | 4 | mod | **gone** | REWRITE against 7.0 galaxy | dropped: 7.0's model pipeline |

### other

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `selfdrive/controls/tests/test_turn_hold_shaping.py` | bosch+vfn | 142 | new | **gone** | REVIEW | dropped: feature not ported |
| `tools/replay/ui.py` | bosch+vfn | 108 | mod | `openpilot/tools/replay/ui.py` | REVIEW | done: replay radar roles on 7.0's raylib UI |
| `starpilot/assets/tests/test_model_pipeline.py` | bosch+vfn | 92 | mod | **gone** | REVIEW | dropped: 7.0's model pipeline |
| `tools/replay/lib/ui_helpers.py` | bosch+vfn | 73 | mod | `openpilot/tools/replay/lib/ui_helpers.py` | REVIEW | done: replay radar roles on 7.0's raylib UI |
| `tools/StarPilot/feasibleparams.txt` | bosch+vfn | 65 | mod | **gone** | REVIEW | dropped: 6.x glue, 7.0 feature owners |
| `selfdrive/locationd/test/test_calibrationd.py` | vfn | 46 | mod | `openpilot/selfdrive/locationd/test/test_calibrationd.py` | REVIEW | done: 3X->C4 reprojection (slice 9.3) |
| `tools/replay/tests/test_radar_debug.py` | bosch+vfn | 40 | new | **gone** | REVIEW | done: replay radar roles on 7.0's raylib UI |
| `selfdrive/locationd/calibrationd.py` | vfn | 33 | mod | `openpilot/selfdrive/locationd/calibrationd.py` | REVIEW | done: 3X->C4 reprojection (slice 9.3) |
| `selfdrive/controls/tests/test_navigation_desires.py` | bosch+vfn | 30 | mod | **gone** | REVIEW | dropped: feature not ported |
| `common/transformations/model.py` | vfn | 16 | mod | `openpilot/common/transformations/model.py` | REVIEW | dropped: per-model warps (9.4) |
| `tools/StarPilot/derive_feasible_params.py` | bosch+vfn | 12 | mod | **gone** | REVIEW | dropped: 6.x glue, 7.0 feature owners |
| `selfdrive/monitoring/policy.py` | bosch+vfn | 11 | mod | `openpilot/selfdrive/monitoring/policy.py` | REVIEW | done: night-star7 only (`night_star_timing`); stock on night-star7-clean |
| `selfdrive/car/redneck_cruise.py` | bosch+vfn | 9 | mod | **gone** | REVIEW | dropped: 7.0 removed redneck cruise |
| `common/tests/test_params.py` | bosch+vfn | 7 | mod | `openpilot/common/tests/test_params.py` | REVIEW | dropped: 6.x params test |
| `common/pid.py` | bosch+vfn | 6 | mod | `openpilot/common/pid.py` | REVIEW | done (slice 1) |
| `selfdrive/car/car_specific.py` | bosch+vfn | 6 | mod | **gone** | REVIEW | dropped: 7.0 brakeHold event covers it |
| `system/updated/updated.py` | bosch+vfn | 5 | mod | `openpilot/system/updated/updated.py` | REVIEW | held: optional updater shallow fetch |
| `selfdrive/car/card.py` | bosch+vfn | 1 | mod | `openpilot/selfdrive/car/card.py` | REVIEW | done: slices 7-8 |
| `selfdrive/car/tests/test_car_specific.py` | bosch+vfn | 1 | mod | **gone** | REVIEW | dropped: 6.x car_specific (gone in 7.0) |
| `tools/lib/api.py` | bosch+vfn | 1 | mod | `openpilot/tools/lib/api.py` | REVIEW | dropped: 7.0 provider system (Konik only on night-star7) |
| `tools/lib/auth.py` | bosch+vfn | 1 | mod | `openpilot/tools/lib/auth.py` | REVIEW | dropped: 7.0 provider system (Konik only on night-star7) |
| `selfdrive/pandad/pandad` | bosch+vfn | 0 | mod | `openpilot/selfdrive/pandad/pandad` | REVIEW | done: rebuilt binaries |
| `starpilot/controls/lib/tests/__init__.py` | bosch+vfn | 0 | new | **gone** | REVIEW | dropped: hidden test package marker |
| `system/camerad/camerad` | bosch+vfn | 0 | mod | `openpilot/system/camerad/camerad` | REVIEW | done: rebuilt binaries |
| `system/loggerd/bootlog` | bosch+vfn | 0 | mod | `openpilot/system/loggerd/bootlog` | REVIEW | done: rebuilt binaries |
| `system/loggerd/encoderd` | bosch+vfn | 0 | mod | `openpilot/system/loggerd/encoderd` | REVIEW | done: rebuilt binaries |
| `system/loggerd/loggerd` | bosch+vfn | 0 | mod | `openpilot/system/loggerd/loggerd` | REVIEW | done: rebuilt binaries |

### build / scripts

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `scripts/model_source_map_v26.json` | vfn | 453 | new | `scripts/model_source_map_v26.json` | REVIEW | dropped: 7.0's model pipeline |
| `scripts/rebuild_tg_artifacts.sh` | vfn | 66 | new | **gone** | REVIEW | dropped: 7.0's model pipeline |
| `scripts/tests/test_model_release.py` | vfn | 29 | mod | **gone** | REVIEW | dropped: 7.0's model pipeline |
| `scripts/host_tool_runner.sh` | bosch+vfn | 19 | mod | `scripts/host_tool_runner.sh` | REVIEW | dropped: 6.x host build plumbing |
| `.gitignore` | bosch+vfn | 8 | mod | `.gitignore` | REVIEW | dropped: 7.0's own ignores |
| `.dockerignore` | bosch+vfn | 5 | mod | **gone** | REVIEW | dropped: 7.0's own ignores |
| `scripts/model_release.py` | vfn | 1 | mod | **gone** | REVIEW | dropped: 7.0's model pipeline |
| `scripts/model_source_map_v22.json` | bosch+vfn | 1 | mod | **gone** | REVIEW | dropped: 7.0's model pipeline |

### controls core

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `selfdrive/controls/controlsd.py` | bosch+vfn | 294 | mod | `openpilot/selfdrive/controls/controlsd.py` | PORT hooks into rewritten controlsd | done (slices 2+5; interpolation, turn hold/shaping, NrdrLearn*, NNFF path not ported by decision) |
| `selfdrive/controls/tests/test_controlsd.py` | bosch+vfn | 120 | new | **gone** | PORT hooks into rewritten controlsd | dropped: steer_limited_by_safety fix is native in 7.0 |
| `selfdrive/selfdrived/selfdrived.py` | bosch+vfn | 37 | mod | `openpilot/selfdrive/selfdrived/selfdrived.py` | PORT hooks into rewritten controlsd | wip (steerSaturated suppression done; reproject ignores are slice 9) |
| `selfdrive/selfdrived/events.py` | bosch+vfn | 27 | mod | `openpilot/selfdrive/selfdrived/events.py` | PORT hooks into rewritten controlsd | done: slice 9 (and steerSaturated in slice 5) |
| `selfdrive/controls/lib/desire_helper.py` | bosch+vfn | 6 | mod | `openpilot/selfdrive/controls/lib/desire_helper.py` | PORT hooks into rewritten controlsd | done (slice 6: Honda-only nudge torque) |
| `selfdrive/selfdrived/alerts_offroad.json` | bosch | 4 | mod | `openpilot/selfdrive/selfdrived/alerts_offroad.json` | PORT hooks into rewritten controlsd | dropped: 7.0 ships Jetlink |

### docs

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `docs/JETLINK.md` | bosch | 255 | new | **gone** | COPY ours | dropped: 7.0 ships Jetlink |
| `docs/HONDA_EPS_CONTROLLER.md` | bosch+vfn | 103 | new | `docs/HONDA_EPS_CONTROLLER.md` | COPY ours | done: rewritten for 7.0 |
| `docs/MODEL_REBUILD.md` | bosch+vfn | 76 | mod | **gone** | COPY ours | dropped: 7.0's model pipeline |
| `tools/replay/README.md` | bosch+vfn | 27 | mod | `openpilot/tools/replay/README.md` | COPY ours | done: replay radar roles on 7.0's raylib UI |

### system / manager

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `system/manager/manager.py` | bosch+vfn | 237 | mod | `openpilot/system/manager/manager.py` | PORT selectively | wip (Honda EPS settings rename/carry-over done; rest todo) |
| `system/manager/accelerator_shutdown.py` | bosch | 72 | new | **gone** | PORT selectively | dropped: 7.0 ships Jetlink |
| `system/manager/process.py` | bosch | 46 | mod | `openpilot/system/manager/process.py` | PORT selectively | dropped: 7.0 ships Jetlink |
| `system/hardware/hardwared.py` | bosch+vfn | 25 | mod | `openpilot/system/hardware/hardwared.py` | PORT selectively | held: 9.5 Chestnut extras (7.0 has flash-before-onroad) |
| `system/manager/process_config.py` | bosch+vfn | 10 | mod | `openpilot/system/manager/process_config.py` | PORT selectively | done: slice 9 (reproject services) |
| `system/hardware/tests/test_usb.py` | vfn | 3 | mod | **gone** | PORT selectively | held: 9.5 Chestnut extras |
| `system/hardware/usb.py` | vfn | 1 | mod | **gone** | PORT selectively | held: 9.5 Chestnut extras |

### params / schema

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `common/params_keys.h` | bosch+vfn | 71 | mod | `openpilot/common/params_keys.h` | PORT keys into 7.0 contracts; rebuild | wip (Honda EPS keys done in slice 2; rest todo) |
| `cereal/custom.capnp` | bosch+vfn | 53 | mod | `openpilot/cereal/custom.capnp` | PORT keys into 7.0 contracts; rebuild | wip (eps* done in slice 2, @11-@19) |
| `cereal/log.capnp` | bosch+vfn | 15 | mod | `openpilot/cereal/log.capnp` | PORT keys into 7.0 contracts; rebuild | done: slice 9 (reproject services) |
| `cereal/services.py` | vfn | 2 | mod | `openpilot/cereal/services.py` | PORT keys into 7.0 contracts; rebuild | done: slice 9 (reproject services) |

### DBC

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `opendbc_repo/opendbc/dbc/acura_ilx_2016_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/acura_mdx_2017_can_ext_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/acura_rdx_2018_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/acura_rdx_2020_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/generator/honda/_honda_common.dbc` | bosch+vfn | 5 | mod | `opendbc_repo/opendbc/dbc/generator/honda/_honda_common.dbc` | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_accord_2017_can_ext_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_bosch_radarless_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_civic_hatchback_ex_2017_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_civic_touring_2016_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_clarity_hybrid_2018_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_common_canfd_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_crv_touring_2016_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_e_advance_2020_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_insight_ex_2019_can_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_odyssey_exl_2018_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/honda_odyssey_twn_2018_generated.dbc` | bosch+vfn | 5 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |
| `opendbc_repo/opendbc/dbc/hyundai_can_refresh_generated.dbc` | bosch+vfn | 1 | mod | **gone** | REVIEW - regenerate from 7.0 sources | done: slice 6 (_honda_common 0x94); generated at build |

### StarPilot glue

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `starpilot/controls/tests/test_starpilot_card.py` | bosch+vfn | 36 | mod | **gone** | RE-HOME into 7.0 feature owners | dropped: 6.x glue, 7.0 feature owners |
| `starpilot/common/starpilot_variables.py` | bosch+vfn | 18 | mod | **gone** | RE-HOME into 7.0 feature owners | dropped: 6.x glue, 7.0 feature owners |
| `starpilot/common/tests/test_starpilot_variables.py` | bosch+vfn | 14 | mod | **gone** | RE-HOME into 7.0 feature owners | dropped: 6.x glue, 7.0 feature owners |
| `starpilot/controls/starpilot_card.py` | bosch+vfn | 8 | mod | **gone** | RE-HOME into 7.0 feature owners | dropped: 6.x glue, 7.0 feature owners |
| `starpilot/common/starpilot_utilities.py` | bosch+vfn | 5 | mod | **gone** | RE-HOME into 7.0 feature owners | dropped: 6.x glue, 7.0 feature owners |

### panda safety

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `opendbc_repo/opendbc/safety/tests/test_honda.py` | bosch+vfn | 17 | mod | `opendbc_repo/opendbc/safety/tests/test_honda.py` | PORT - safety critical (Nidec hybrid brake) | done (slice 4: TestHondaNidecHybridSafety) |
| `opendbc_repo/opendbc/safety/modes/honda.h` | bosch+vfn | 10 | mod | `opendbc_repo/opendbc/safety/modes/honda.h` | PORT - safety critical (Nidec hybrid brake) | done (slice 4: larger of both brake fields, no hybrid param) |

### opendbc other

| File | From | +lines | Ours was | 7.0 path | Decision | Status |
|---|---|---:|---|---|---|---|
| `opendbc_repo/opendbc/car/interfaces.py` | bosch+vfn | 11 | mod | `opendbc_repo/opendbc/car/interfaces.py` | REVIEW | done: slices 2-3 (controller factory) |
