# Sapander Honda Civic Bosch radar test — initial findings

**Status: PRELIMINARY — NEEDS VALIDATION AND FURTHER INVESTIGATION**

This package contains two contiguous rlog segments from the same test drive
and the initial offline observations. These findings are evidence for the next
investigation, not a final root-cause determination and not a road-test signoff.

## Log provenance

- Route/drive prefix: `00000001--cb2bbfc630`
- Vehicle: `HONDA_CIVIC_BOSCH`
- Branch: `night-star-bosch-radar`
- Embedded git SHA: `cba95d23f17ce629b16841138adb76fe7262a632`
- Embedded log state: `dirty=false`
- Dongle: `3681db0677b75d8c`
- Device: `tici`
- Software version: `0.11.2`
- Relevant parameters: `AlwaysOnLateral=1`, `AlwaysOnLateralLKAS=1`,
  `AlphaLongitudinalEnabled=1`, `BoschARadar=1`

The attached file is segment 5. The local Downloads file is segment 6. Their
measurement windows are contiguous, with a small timestamp overlap:

| segment | file | first/last actual service time |
|---|---|---|
| 5 | `00000001--cb2bbfc630--5--rlog.zst` | `1133.545918785` – `1193.575595893` |
| 6 | `00000001--cb2bbfc630--6--rlog.zst` | `1193.559626160` – `1253.577932563` |

Times in the interval summaries below are segment-relative to the first
actual service message, not route-wall-clock time.

## What the two segments show

The sustained full-torque behavior is present in the logged control stream,
not merely in a replay overlay:

- Segment 5: 10 full normalized-torque runs, approximately 15.225 seconds
  total.
- Segment 6: 12 runs, approximately 34.123 seconds total.
- The clearest segment-6 run is approximately `15.741–29.121 s` and lasts
  `13.380 s`, while vehicle speed is roughly 25–39 mph.
- `carControl.actuators.torque` reaches `1.0` during these runs and the
  corresponding control output is observable in the recorded stream.

The vehicle is in Always-On Lateral rather than longitudinal Bosch radar
control for these segments:

- `selfdriveState.active=false`
- `carControl.longActive=false`
- `carControl.latActive=true` except during six recorded EPS fault samples
- `starpilotCarState.alwaysOnLateralEnabled=true`

This excludes radar lead selection and Bosch longitudinal control as the
direct cause of the sustained lateral torque event.

## EPS status and fault evidence

Raw CAN `0x18F` was decoded using the existing Honda `STEER_STATUS` mapping:
the status is the high nibble of byte 4.

| raw status | interpretation in current DBC/code | segment 5 | segment 6 |
|---:|---|---:|---:|
| `0` | normal | 3500 | 1867 |
| `3` | low-speed lockout | 2501 | 4126 |
| `5` | `fault_1` | 0 | 6 |
| `7` | permanent-fault value | 0 | 0 |

The six segment-6 status-5 samples cluster around segment-relative `30.16 s`
and `39.68 s`. They align with six rows where `latActive` drops, PID output
and commanded torque go to zero, and then control resumes. The raw stream does
not contain status `7`; the current software nevertheless flags both
temporary and permanent steering faults for status `5`. The reported
dashboard-level permanent fault therefore needs separate validation against
the actual EPS behavior and the Honda status mapping.

Recorded steering-torque maxima were approximately 2468 in segment 5 and 2320
in segment 6. This does not fully validate or disprove the driver's reported
1400–2000 override range, but it confirms that the logs include torque values
above that range.

## Strongest current control-state lead

`controlsState.lateralControlState.pidState.i` is exactly
`+0.843778193` on every active row in both segments. It becomes `0.0` only on
the six inactive/fault rows and returns to `+0.843778193` immediately when
control resumes.

Full torque also occurs with nearly zero instantaneous angle error, for example:

- segment 6 near `20.006 s`: angle error about `0.045°`, output torque `1.0`
- segment 6 near `25.915 s`: angle error about `0.005°`, output torque `1.0`

This is consistent with a persistent PID integral/freeze/reset problem rather
than a simple large steering-error response. It does **not** yet prove why the
integrator is held at that value: private controller state such as
`freeze_integrator` and `steer_limited_by_safety` is not fully exposed in the
rlog.

The current inactive branch zeroes output state but does not call the PID
object's `reset()`, so the persistence across an EPS fault is a concrete code
fact requiring a controlled offline test. The integral was already present
before the first long saturation, so the fault itself is not sufficient to
explain the initial onset.

## Scheduling context — plausible, not proven

The current branch retains the older placement where `card` and `controlsd`
both run on processor 4 at the same priority. The RiskyBiscuit workload
isolation change (`fffd162f28`) moved `controlsd` to processor 5, but
`c2a2570341` reverted that change. The embedded tip is later
`cba95d23f17...`, whose tip change is unrelated Flask threading; it does not
restore the workload-isolation placement.

The logs show heavy cumulative CPU time for both processes on that shared
processor. Message cadence is mostly near 100 Hz, with maximum observed
`controlsState` gaps of approximately 29 ms in segment 5 and 24 ms in segment
6. This makes scheduling pressure worth an A/B replay, but the available logs
do not establish it as the cause of the 10–13 second full-torque periods.

## Preliminary diagnosis

**Most likely area:** Always-On Lateral PID state, especially a retained
integral combined with an unexplained integrator-freeze or safety-limited flag.

**Separate confirmed event:** EPS status `5` produces six logged fault samples
and temporarily disables lateral output. Raw status `7` was not observed, so
the permanent-fault interpretation needs verification.

**Not supported by these logs:** Bosch radar/longitudinal lead control as the
cause of the sustained lateral saturation. Longitudinal control is inactive.

**Still open:** whether shared-core scheduling contributes; whether the
integral should be reset on the relevant AOL/EPS transitions; why the
integrator remains frozen while active; and whether the status-5 handling is
overly conservative or reflects a genuine EPS fault.

## Required validation before any road test

1. Instrument an offline replay/control diagnostic for `pid.i`,
   `freeze_integrator`, `steer_limited_by_safety`, `steeringPressed`, and the
   active/AOL transitions at the exact segment-5/6 windows.
2. Compare the current placement with the reverted workload-isolation
   placement without changing radar or longitudinal logic.
3. Verify the raw `0x18F` status-5 interpretation against Honda EPS behavior and
   the permanent-fault flag logic.
4. Add regression coverage for integral reset/ownership and for full-torque
   behavior at near-zero angle error before considering a vehicle test.

## Packaged file hashes

These hashes identify the raw files included in this package:

```text
003bf7980c1551e4e01ddbac02fdabb1bc1bb287be53b289b2b7a7bee0605c42  00000001--cb2bbfc630--5--rlog.zst
40e0e84c541616e3c8f5d1263337fcf59fa7488a20cb499e8b23bc5c6fd36f22  00000001--cb2bbfc630--6--rlog.zst
```

No production code was modified, committed, or pushed for this package.
