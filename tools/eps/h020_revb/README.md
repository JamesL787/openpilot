# H020 rev-b: TGG response + Clarity limits

This is a locally generated **offline candidate**, requested by the owner after the A–E implementation audit. It is not an MR.ONE or Honda release. The earlier instruction to leave calibration/firmware untouched was superseded by the explicit request to rebuild H020 and match its controller calibration. Fitting tools, the numerical controller core, private/global PID, geometry/rack modules, res timing and unrelated vehicle tunes remain unchanged.

Parent port commit: `86aa8c48506eada4e86f167346e0256dfa2221fe` on `tea-h020-eps-port`. Controller source pin: `ns-bosch-radar-testing` at `92428ab490b3085ea523f79cc6a32d392a057b56`. res base: `01e22f5921d9dfd49235f5867f54d9ec0bdccbaf`. The build ID retains October 22, when this candidate was prepared; final review continued October 23.

## Selected behavior

The owner's final selection was **TGG response + Clarity limits**, retaining TGG vehicle-side donor coefficients. This does not mean copying Clarity's geometry or its command response.

| Field | Selected H02B candidate | Source / H020 offset |
|---|---|---|
| Native command X, row 0 | `0,226,311,495,656,887,1108,1552,1774` | H020, `0x13794` |
| Corrected command Y, row 0 | `0,3818,5258,8378,11099,15003,18747,26253,30002` | TGG corrected response resampled onto H020's native X, `0x13812` |
| P X, row 0 | `0,237,473,709,946,1182,1419,1655,1892` | TGG rev-b, `0x13AE2` |
| P Y, row 0 | `117,148,184,220,245,257,263,265,265` | TGG rev-b, `0x13B60` |
| Speed envelope X | `0,50,100,150,200,260,300,350,400` | Clarity, `0x135E4`; model interprets axis as 0.5 km/h counts |
| Speed envelope Y | `1774,1774,1774,1774,1774,1330,1330,1330,1330` | Clarity, `0x13662` |
| Command key ceiling | 1663 | Existing H020 header, already same as Clarity |
| P / D / final output ceilings | `7373 / 1774 / 9000` | `0x13890`; already identical to Clarity |
| Speed clamp words | `0 / 400` | `0x135BC`; already identical to Clarity |
| Tracker | Separate 4250 and 3200 variants | `0x1378E` |
| NORM / added FF | 1650 / KFF45 | Existing H020 code, unchanged |

Rows 0–5 receive the selected command/P response and Clarity envelope. Row 6's command/P/D data is restored from the original H020 stock image; its envelope is retained. All five searched variant selectors remain row 0. The native command X axes of rows 0–5, A/B geometry, program instructions, FF cave, A280 tables, boot and loader remain byte-identical to the corresponding H020 parent. The only other application edits are seven same-length identity literals (`39990-TEA,H020` → `39990-TEA,H02B`) and two checksum words. Exactly **270 bytes** differ from each PTM parent.

At the model's speed scaling, the effective key ceiling is 1663 through 100 km/h, about 1626 at 110, 1478 at 120 and 1330 from 130 upward. This is Clarity's actual envelope, not a flat 1774 limit. It is lower than the old H020 envelope around 120–130 km/h and higher at 150+ km/h.

The corrected TGG reference is `PTM_FIX_FAMILY_20261016/verify_TGG_20261019/fixed.full.bin`, SHA-256 `d8052b44772aacd8cd895d59ccaf89749fe67bfc05a8a8cd55212a3a0e1a13fa`. Its native command axis is `(0,103,263,459,660,862,1111,1549,1774)` with Y `(0,1740,4443,7769,11167,14579,18798,26202,30002)`. Its slope is about 16.9 R5/key, whereas the Clarity command response is about 18.04 R5/key. The candidate uses the former. Because 1774 lies above the reachable 1663 key clamp, the last H020 endpoint is extrapolated from the last reachable segment to preserve the target response through 1663.

The Clarity reference SHA-256 is `906dcd14422450803487475a621fddd9d359ac2e0ea58498772d3c0dbb82d572`. Exact source paths/hashes and interpreter provenance are in `SOURCES.json`; the original inputs are retained in `testdata/inputs.zip` for reproducibility. Originals outside this port repository were only read.

## What “similar to TGG” establishes

Actual images show byte-identical H020/TGG A/B geometry at `0x1306C`, `0x130A8`, `0x130E4`, `0x13120` (60 bytes each). H020 P/D code `[0x29AB8,0x29C20)` equals TGG `[0x29B18,0x29C80)`, and H020 A280 code `[0x299F0,0x29AB8)` equals TGG `[0x29A50,0x29B18)`. The 70-byte FF cave at `0x4F1CC` differs only in its resume displacement at `0x4F207`. This supports reuse of the control-law model and a TGG donor starting point.

The October 11 H020 command map was nevertheless different: its segment slopes were 8.5, 35.4, 19.1, 22.2, 16.8, 19.1, 15.4, 13.7 R5/key. Matching estimator/P/D code did not make that map equivalent to the corrected TGG image. The old `H020` calibration and October 11 images retain this issue. H02B corrects the command/P data response offline; no installed H020 image is changed by creating these files.

The new `H020_REVB` profile is extracted from the generated H02B tables, including its Clarity envelope. It keeps TGG load `(-15.67,-0.157,-5.449,-388.8,75.77,-0.6084)`, TGG rack table, P trims `(1.15,1.25,1.15)`, I trims `(0.75,0.95,1.0)`, and the four-point Civic Bosch base P/I schedule from the pinned controller source. H020's firmware-derived R6/geometry remains its own. Donor load, rack and trims remain **inferred on H020**, with no H020 route fit or holdout validation. Sharing these fields is not evidence of equal physical loop gain, particularly with a different speed envelope or tracker.

## Image identities and matching controller

| Tracker | Required `ptm_build` | RWD SHA-256 |
|---|---|---|
| 4250 | `20261022b-tgg-claritylimits-trk4250` | `e1ad753e11986b9392fc9a1baca8f46605d25bb538b00ed7bf2bec57f2264261` |
| 3200 | `20261022b-tgg-claritylimits-trk3200` | `0289f9178016effd707de92e5d4923254587d771bbca02e203b1ab9aadb2877b` |

Full-image SHA-256: 4250 `a5e87ece9039c820993f0beb3f8f7f9597c09e94ec6518d827be3855cbcb755d`; 3200 `b330ef7150fbf819bc9764c7795cd63d571e14f964b6f8ed7bbec0c851b40ce3`. Per-image JSON contains payload hashes and the complete edit list.

`h020_builds.py` binds each declaration to its image hashes, tracker and controller profile. The new family must report exact modified EPS ID `39990-TEA,H02B` and pair with a rev-b declaration; legacy `39990-TEA,H020` pairs only with an October 11 declaration. Cross-family selections refuse in card, activation loading and controller selection. The profile reaches the actual feedforward core and rack constructor through the one startup snapshot. Configurations supplied with the package are **disabled templates**.

Missing/disabled/invalid configuration on the new H02B image sets `dashcamOnly`, so it cannot silently steer with the legacy map/controller. Stock/unrelated EPS and legacy disabled/missing configuration retain the prior res path. New H02B without the provisional Civic Bosch platform association also stays passive. The existing exact, non-fuzzy firmware gate still requires the other necessary ECUs; the new literal only identifies this generated image family and is not evidence of the vehicle's platform. The sidecar/CarParams runtime guard still latches zero on a card-only configuration/profile change until controlsd restarts; it polls at most once/second.

Both tracker variants use the same new family ID. **`ptm_build` and tracker remain owner declarations, not an ECU image/hash readback.** The seven patched version records and RWD header are checked statically; an actual post-flash diagnostic query has not occurred. A family string cannot prove every application byte or the installed tracker.

The output folder includes `CONTROLLER_FROM_86aa8c485.patch`, a reviewable controller delta from the exact port parent above, plus disabled configs, both image/container variants, hashes and evidence. It is not the complete port from stock res and contains no installer. The full current implementation is in the local Git commit. `REPRODUCTION_INPUTS.zip` in the output folder duplicates the hash-pinned test inputs for standalone image review.

## Reproduction and offline evidence

Run from the port repository using ordinary host Python; no flasher is invoked:

```sh
python3 -m zipfile -e tools/eps/h020_revb/testdata/inputs.zip .git/h020-revb-reproduction-inputs
python3 tools/eps/h020_revb/build.py --inputs .git/h020-revb-reproduction-inputs --output .git/h020-revb-reproduction --response tgg
python3 tools/eps/h020_revb/verify.py --inputs .git/h020-revb-reproduction-inputs --candidate .git/h020-revb-reproduction --response tgg
H020_TEST_PYTHON=/Users/jameslichtenstiger/nrdr/openpilot/.venv/bin/python bash tools/lateral/run_h020_tests.sh
```

The builder refuses unexpected input hashes and existing output directories. The RWD block starts at `0x4000`, length `0x4C000`; its payload equals that full-image slice. The original proven H020 transport/cipher/header/key fields are preserved, with the new family added as a third accepted identity using the same H020 loader key. Independent checks cover the exact byte-change whitelist, stock row 6, all protected regions and both application checksums/file checksum.

`verify.py` executes actual ROM instructions in a strict SH-2A interpreter, rather than disassembly text or a table-only simulation:

- H020 command function `0x29746`: 3,605 signed cases per row across seven rows.
- P/D function `0x29AB8`: 635 cases per row; checks P, D, prior-error writes and clamps.
- Final wrapper `0x297C2`, FF cave and A280: 200 cases per row. The driver-governor function `0x298F2` is explicitly stubbed with synthetic gains; these tests do **not** validate live blend/gate values.
- Corrected TGG command function `0x297A6`: comparison at all 3,327 reachable signed keys. Observed maximum difference **2 R5 counts**, within the declared 16-count resampling bound.
- Actual H020 loader range gate `0x52202`, block lookup `0x521C8` (blocks 0 and 9 at endpoints), and decrypt function `0x50A00` for all 256 byte values, on both tracker images. Only watchdog helper `0x54744` is stubbed. This verifies those routines, not a complete flash transaction.

The 3200 variant's only differences from 4250 are tracker bytes and checksum words; the full control-law sweep therefore runs once on 4250. Structural and loader checks run on each. `VERIFICATION.json` records the exact image/RWD hashes associated with these results. The input archive's hashes are checked independently before CLI verification; assertions must be enabled.

The regression command passes **120 tests**, including the previous 86. Fourteen new startup cases were run against unchanged `86aa8c485` production modules and all fourteen failed; they pass with this implementation. Two additional matcher cases demonstrate that an H02B EPS plus matching other ECUs passes the existing exact matcher, and missing required radar still fails. Tests run actual card/controlsd initializer and state-control bodies, real setup_interfaces, real Honda interface and CarController/CAN packing with host I/O replaced. They are offline execution, not a complete daemon/device boot.

## Unresolved limits

1. October 11 H020's TargetMap-D/native-axis mismatch remains on those images. H02B repairs the selected data response offline; TGG load/trim transfer and physical loop gain are not validated on H020.
2. Pre-table shaping gates, blend inputs and driver-governor behavior on the real H020 are unverified. The forward model still assumes unity shaping.
3. The tracker/build declaration is not ECU image readback. No flash or diagnostic query was performed.
4. Bosch versus Nidec remains unverified without real CarParams/carFw. TEA appears under both platforms. No stock H020/H02B or speculative ECU fingerprints were added.

No push, installation, flash, Discord message or vehicle test was performed. All writes were confined to this port repository.
