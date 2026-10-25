# H020 Honda EPS controller port for LiMing's C3XL `res`

Status: **offline prototype, not vehicle-tested.** Scope: port `HondaEpsLateralCore` from `ns-bosch-radar-testing` onto MR.ONE's `res`, with the
TGG-A120 vehicle calibration as the H020 baseline. The rev-b firmware (it reports the ordinary modified ID `39990-TEA,H020`) is built and delivered **outside this branch**.

## Inputs

- Controller source: JamesL787/openpilot `ns-bosch-radar-testing` `92428ab490b3085ea523f79cc6a32d392a057b56`.
- Target: `https://jihulab.com/mr-one/openpilot` `res` `01e22f5921d9dfd49235f5867f54d9ec0bdccbaf`.
- LiMing's archive `res_code_fixed.tar.gz`, SHA-256 `9e66df6605d5b0039b6c8763f485839b72d7968ebb30c42f4de9e1bccb0d3974`: 443 common `.py/.capnp/.h/.sh`
  paths have blob hashes identical to public `res`. The archive omits `opendbc_repo` and other dependencies, so this says nothing about those or about
  device binaries. It is not an installable checkout.

## What is ported

- `honda_eps_firmware_ff.py` (numerical core, source-identical except two imports), a private copy of the source PID (res's global PID differs and is unchanged),
  `honda_eps_rack_map.py`, and H020's position table (`honda_eps_h020_geometry.py`).
- `LatControlHondaEps(CP, CP_SP, CI)`: res update signature and existing PID log schema; 300 deg/s desired-angle slew (initialized at the wheel angle on
  engagement: a res adaptation), output filter 0.1 s, the source driver-press detector (feeds feedforward/integrator only), 0.1 s dropout ride-through,
  non-finite input rejection. Not ported: telemetry, command-delay head selection, model-delay schedule, override fade (res has none).
- **Selection follows the source branch's modified-EPS rule.** The comma in the EPS string marks modified firmware. The H020 controller is used when
  CarParams has a Civic Bosch fingerprint, the modified EPS ID `39990-TEA,H020`, a PID tune and the linear `[0,3840]` map. `interface.py` sets that
  map and the Civic Bosch/TGG base PID (P .018/.024/.048/.060, I .006/.008/.016/.020, kf 0) for exactly that case, after res's legacy modified-EPS block.
  Flashing the rev-b image is the opt-in; there is no config file, sidecar or new Params key.
- Everything else keeps res behavior: any other EPS string (stock `-H020`, the earlier modified `,H020`, other cars, other platforms) is unchanged. The only
  fingerprint added is `39990-TEA,H020`.
- If `setup_interfaces` (EnforceTorqueControl or NeuralNetworkLateralControl) replaces the tune afterwards, `controlsd` logs an error and runs the generic
  controller, as the source branch would; it does not stop.

## Calibration (one: rev-b)

`honda_eps_calibrations.H020`, keyed by `39990-TEA-H020`.

**The string cannot tell the images apart.** Like every other PTM rev-b, the rev-b image reports the same ID as the earlier (2026-10-11) H020 PTM images, whose command map has the TargetMap-D mismatch. The car must be on the rev-b image (and the tracker 4250/3200 is likewise unreadable); a car on an older image would run this calibration against a different map.

| Field | Source |
|---|---|
| Command map row 0, P row 0, envelope, key clamp 1663, NORM 1650 | rev-b image (`h020_firmware_evidence.json`) |
| Command map | TGG-A120 rev-b response resampled onto H020's native key knots; within 2 R5 counts of the TGG image over all 1663 keys |
| P table, D 737, clamps 7373/1774/9000, A/B geometry, P/D and A280 code | identical to TGG-A120 rev-b |
| Speed envelope | **Clarity limits** (1774 to 100 km/h, 1330 from 130 km/h); TGG rev-b row 0 is flat 1774. The one deliberate difference |
| R6 | firmware-derived from H020 Table A and NORM 1650: -153.74 at centre (not measured on H020) |
| Column load | TGG-A120 donor with `k0` -7.8 (TGG -15.67) and friction -285 (TGG -388.8) fitted on LiMing's first H020 route; `k1`, `c`, bias and roll are the TGG's |
| Rack, P/I trims, base PID | TGG-A120 donor, **inferred on H020** |

## Driver-override settings (H020 only, set over SSH)

His UI is the prebuilt Qt `ui` binary (no source in `res`) and `res` ships no C++ `Params` sources, so new Params keys or UI rows cannot be built. The three
settings are plain files in the params directory, read about once a second; a missing, empty or non-numeric file means the default, and out-of-range values
are clipped. They apply only to the H020 (Civic Bosch + `39990-TEA,H020`); every other car keeps `res` behavior.

| File in `/data/params/d/` | Default | Range | Meaning |
|---|---|---|---|
| `HondaDriverOverrideThreshold` | 1800 | 500-5000 | `STEER_TORQUE_SENSOR` units above which the wheel counts as pressed (`res` stock for the Civic Bosch is 1200) |
| `HondaOverrideFadeDownSecs` | 0 | 0-10 | 0 cuts the torque request the moment an override is detected |
| `HondaOverrideFadeUpSecs` | 0.5 | 0-10 | authority returns over this long after the override ends (and after every engage) |
| `HondaEpsFeedforwardScale` | 1.0 | 0-2 | multiplies the firmware-inversion feedforward (the calibrated behavior is 1.0) |
| `HondaEpsPidScale` | 1.0 | 0.25-3 | multiplies the residual PID's P and I |

```sh
echo -n 1800 > /data/params/d/HondaDriverOverrideThreshold   # 1200 restores res's stock value
echo -n 0.5 > /data/params/d/HondaOverrideFadeUpSecs
```

The override uses the source branch's detector (opposing or near-zero-command driver torque latches at once, same-direction torque after 0.28 s). While an
override is latched LKAS is dropped (`STEER_TORQUE_REQUEST` off), so a fade-down above 0 only changes the controller's own state, not what the EPS is sent.
The cut skips `res`'s 3/s torque delta limit, which would otherwise stretch a 0 s fade-down to 0.33 s. Outside an override that limit still applies.

## Tuning on the car

- **Timing.** `res` runs a plan model (his log: the action curvature equals the plan at the told delay + 0.1 s smoothing), so the delay the model is told is the
  timing knob, 1:1. With Live Learning Steer Delay off the told delay is `steerActuatorDelay` (0.10 s for the Civic Bosch) + `LagdToggleDelay`:
  `echo -n 0.03 > /data/params/d/LagdToggleDelay`. On his first route (told 0.25 s) the car ran 0.13 s early; its command-to-yaw lag was 0.24 s at 3-6 m/s,
  0.18 at 6-9, 0.14 at 9-12 and 0.12 at 12-18. Set it over SSH: editing LAF or the delay in the UI used to flip `EnforceTorqueControl`.
- **Enforce Torque / NNLC no longer replace the H020 tune** (`sunnypilot/selfdrive/car/interfaces.py`): on a Civic Bosch with `39990-TEA,H020` the PID tune stays and a
  warning is logged. Every other car is unchanged.
- **Column load.** `k0` and friction were refit on his first route (see the table above); the fit assumes the rev-b image, covers 3.7 min at 64 km/h or less,
  and `bias` and roll are not identifiable from it.

## Not established

- Installed image: nothing reads it back from the ECU; the ID is shared with the older images (above).
- Bosch versus Nidec: `res` lists `TEA-T020` under the Nidec Civic and `TEA-T330/T820` under Civic Bosch and has no `H020`. H020's Table A equals the C020/TGG
  (Bosch) one, which supports Bosch-class, but a real CarParams/carFw from the car is needed.
- The installed image and tracker (4250 or 3200): the EPS string cannot distinguish them. Nothing reads the image back from the ECU.
- Pre-table shaping gates/blend inputs on H020 (the forward model assumes unity); R6's motor-to-angle constant on this hardware; TGG load/trims on H020 hardware;
  res plan timing. No H020 route data exists.

## Tools

`inspect_h020.py` (read-only CarParams report); `fit_yaw_scale.py`, `fit_rack_map.py`, `fit_column_load.py --calibration civic_tea_h020`, `plan_timing.py` for the
H020 route fit. Run from the checkout root with `PYTHONPATH="$PWD:$PWD/opendbc_repo"`. The fit tools were not re-audited here.
Required logs for a fit: two or more complete drives with CAN 0x94, sendcan 0xE4, carState, controlsState, modelV2, liveParameters, GPS, plus the full CarParams/carFw.

## Tests

`H020_TEST_PYTHON=<python> tools/lateral/run_h020_tests.sh` (47 tests, res's real CarParams/PID-log schemas, real `get_params`/`get_params_sp`, the real `controlsd`
selection branch executed from its AST, real `CarControllerParams` E4 scaling). Offline only; `setup_interfaces` itself needs the native Params binding, so its
torque-tune replacement is reproduced by the same `configure_torque_tune` call. No boot, ECU query, CAN trace or road behavior is claimed.
