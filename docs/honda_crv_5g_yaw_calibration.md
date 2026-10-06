# Honda CR-V 5G VSA yaw calibration

This is the retained evidence for enabling `carState.yawRate` on `HONDA_CRV_5G`.
It is a measurement of the vehicle's VSA sensor (`0x094 KINEMATICS`), not an EPS
firmware-table inference.

## Artifact binding

- Route: `00000013--da43527a2c`
- Logged OpenPilot commit: `2f1f2aadef649c3c8c3ae1582ce26bb6cb259a50`
- EPS: `39990-TLA-A040`
- Input: 24 retained full rlog segments; route data remains external and uncommitted
- Ordered segment-manifest SHA-256: `78d149b01973179410c3dca7c845b95f6d57c87023daae9b049d0e84d37d4464`
  (SHA-256 of the sorted `segment/rlog.zst` SHA-256 lines)
- Analysis implementation commit: the commit containing this document

The input contained 143,904 `0x094` frames on powertrain bus 1, 143,715
`carState` samples, 28,278 valid `livePose` angular-velocity samples, and 1,401
GPS fixes. There were 44,082 stopped frames with `vEgo < 0.01 m/s`; their raw
yaw count had mean 509.531, median 510, and standard deviation 0.531 count.

## Scale and direction correction

The GPS fit integrates raw yaw counts between moving, approximately straight
endpoints. It retained 217 windows across segments 2, 3, 8, 13, 15, 19, 20,
21, and 22. A joint least-squares fit of the production decoder form was:

```text
yaw_deg_s = 0.24455268 * (raw_count - 509.531)
            + 0.49019554 * clockwise_ramp(raw_count)
```

The heading residual was 1.34 degrees RMS across those overlapping windows.
The production calibration rounds this to `(0.245, 509.5, 0.49)`, matching the
resolution justified by one route and the sensor's quarter-degree nominal
quantization.

`livePose.angularVelocityDevice.z` independently confirms the sign. With a
40 ms relative log alignment, the instantaneous fit was 0.24012 degree/s per
count plus 0.253 degree/s clockwise, correlation above 0.9996 on both turn
directions. As on the measured Civic, the device gyro reads lower than the GPS
heading integral; the GPS scale is retained because it measures vehicle heading
end to end rather than reproducing another yaw sensor.

## Plan timing result

Running `tools/lateral/plan_timing.py` on the same 24 segments produced:

```text
entry                 +0.06 s   (306 frames)
exit                  +0.09 s   (255 frames)
all turns 5-12 m/s    +0.08 s   (1302 frames)
```

Positive means the car was late relative to the model plan. Therefore the
Civic/Clarity town command delay from trung PR #17 must **not** be copied to the
CR-V: an added delay would move this route in the wrong direction. The route ran
the normal PID controller, so it also does not validate the specialized
`LatControlHondaEps` controller or provide the CR-V column-load model that its
software inversion requires. This is separate from FeedforwardV1 already present
in the owner's EPS firmware: the firmware term is confirmed statically, but it
does not supply the OpenPilot controller's vehicle-load fit.

## Verification boundary

`[CONFIRMED offline route]` Bus, zero, sign, GPS scale, direction correction,
and the no-command-delay decision are bound to the route and logged commit
above. Unit tests assert real route frames through the production CAN parser and
consumer field.

This is not live closed-loop validation. It does not prove timing on the current
branch, with firmware VGR enabled, or with a different EPS flash. No CR-V
firmware-inversion feedforward controller is enabled by this change.
