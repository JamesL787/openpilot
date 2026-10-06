# Honda CR-V 5G firmware-inversion lateral controller

This records the CR-V-specific calibration used to select the existing
`LatControlHondaEps` logic for `HONDA_CRV_5G`. It does not introduce another
control law: joining, fading, filtering, residual PID, firmware inversion,
driver override, and telemetry remain the Civic/Clarity implementation.

## Artifact binding

- FF45 full image:
  `39990-TLA-A040_tq30000_a9000_t9_ff45_8cf8e537_DO_NOT_FLASH_full.bin`
- Image SHA-256:
  `d5dc04a839af2c473e103f4f9d448bf600e26ea0531521a58da61e2267dc351e`
- Load-fit route: `00000006--82bb552a2c`
- Logged OpenPilot commit: `49e6610d08373bb8512ccce38d2f75c61656325e`
- Compact drive SHA-256:
  `36f740e698093609d6996b5b97eaa28dacb75ccb87028f170a7d4ad997caa24b`

The firmware image and compact drive remain in the Honda firmware repository;
they are not runtime dependencies. The exact constants, fit result, hashes, and
reproduction tool are folded into this repository.

## Firmware calibration

The image supplies the exact nine-point command and P-gain tables used by the
controller calibration. It also supplies command clamp 1774, output scale 256,
and FeedforwardV1 Kff 45. OpenPilot's normalized lateral output currently maps
to 4096 E4 counts for the modified CR-V profile.

Route `00000006--82bb552a2c`, recorded with feedback normalization 1450,
measured `feedback_R6 / steeringRateDeg = -105.70439496`. The FF45 image uses
normalization 1650, so its DC conversion is
`-105.70439496 * 1650 / 1450 = -120.28431151` counts/(degree/s). Tracker alpha
changes phase but not that DC gain.

## CR-V load fit

Run:

```bash
python tools/lateral/fit_crv_eps_load.py /path/to/drive-82bb552a2c.json
```

The fit uses 9,784 samples with speed above 2 m/s, active command, no steering
press, driver torque below 400, and the hands-off Q8 scale of 256. Its target is
the firmware output reconstructed exactly by the retained V5 telemetry:

```text
load = -9.09927 * angle
       -0.0225716 * angle * speed^2
       -5.24359 * angle_rate
       -259.312 * tanh(angle_rate / 5)
       -55.7274
```

Alternating 60-second block holdouts produce R² 0.8017 and 0.8392. The compact
drive did not retain roll, so the roll coefficient is deliberately zero rather
than borrowed from another car.

## Runtime boundary

`NrdrLatEpsFirmwareFF` remains the gate. On a modified CR-V it now selects the
same controller class as the Civic/Clarity, but with `CRV_5G_A040_FF45`, the
CR-V load fit, and neutral P/I multipliers because the CR-V CarParams already
carry their speed-scheduled gains. No added command delay is used: route
`00000013--da43527a2c` measured the normal-PID CR-V approximately 0.08 seconds
late, so copying the Civic/Clarity delay would move in the wrong direction.

This is static, unit, and offline telemetry evidence. It is not a road test of
the controller, current FF45 firmware, firmware VGR, or the closed steering loop.

## Current-device firmware confirmation

After the implementation, the comma at `192.168.20.80` was inspected read-only.
Route `00000037--2683763b26`, segment 56 (logged OpenPilot commit
`c12c15fd2350972befede744a7e302d4737dd106`, rlog SHA-256
`2737eaa5e7eb98c0d0dc90b722f378bba29e41e5eb1ff00fde785892226b7fd5`)
contains 2,900 complete nonzero V5 telemetry groups. The measured term added
between `pd_out` and the scaled pre-clamp output matches `45 * reference_R5 /
1024`: correlation 0.99865, fitted slope 0.99929, intercept -0.725 count, RMS
5.74 counts, and 95th-percentile absolute error below one count. This confirms
that Kff 45 is running in the owner's EPS, not merely present in the retained
firmware artifact.

A same-timestamp exploratory load refit across nine segments was deliberately
not adopted: per-segment holdout R² ranged from 0.33 to 0.91 because EPS output
leads the resulting wheel motion and requires the extractor's alignment model.
The aligned compact-drive fit above remains canonical until the current route is
run through that complete alignment pipeline.

The comma was still at source commit `87d17c83d97e6cbad9f2ecc7ed02613164e16ee9`
when inspected, with `NrdrLatEpsFirmwareFF=True` and
`NrdrLatUseFirmwareVgr=False`. The new controller commit was not installed or
road-tested during this inspection.
