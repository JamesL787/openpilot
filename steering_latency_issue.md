# Steering Control Latency Issue

## The Problem

When exiting a turn, the car takes too long to straighten the wheel. This causes:
- Delayed straightening
- Potential overshoot into opposite lane
- Over-correction as controller tries to catch up

---

## Root Cause: System Latency Chain

```
Controller → CAN → EPS Motor → Steering Rack → Tire Slip → IMU
    ↓           ↓        ↓           ↓            ↓          ↓
   10ms      30ms      50ms       50ms        30ms       10ms
                                              Total: ~180ms
```

The controller calculates torque based on where the car **will be** in 180ms, not where it is **now**.

---

## The Buffer System

**File:** `sunnypilot/selfdrive/controls/lib/latcontrol_torque_v0.py`

**Buffer initialization (lines 66-71):**
```python
# Line 25
LAT_ACCEL_REQUEST_BUFFER_SECONDS = 1.0

# Lines 67-71
self.lat_accel_request_buffer_len = max(1, int(LAT_ACCEL_REQUEST_BUFFER_SECONDS / self.dt))
self.lat_accel_request_buffer = deque(
    [0.0] * self.lat_accel_request_buffer_len,
    maxlen=self.lat_accel_request_buffer_len
)
```

**Buffer population (line 132):**
```python
# Line 132
self.lat_accel_request_buffer.append(future_desired_lateral_accel)
```

**Buffer read for setpoint (lines 128-140):**
```python
# Line 128
delay_frames = int(np.clip(lat_delay / self.dt, 1, self.lat_accel_request_buffer_len))

# Line 129
expected_lateral_accel = self.lat_accel_request_buffer[-delay_frames]

# Line 140
setpoint = lat_delay * desired_lateral_jerk + expected_lateral_accel
# Line 141
error = setpoint - measurement
```

---

## Why Unwinding Fails

**During a turn:**
```
Buffer: [0.05, 0.05, 0.05, 0.05, ...]  # high curvature
Setpoint: based on old high values
Controller: commands high torque (correct)
```

**During unwind:**
```
Frame 1: desired_curvature drops 0.05 → 0.02
Frame 2: buffer appends 0.02, reads buffer[-15] = still 0.05
         Setpoint: still expects high curvature
         Error: positive (car not turning enough)
         Controller: adds MORE torque to catch up
         
Buffer clearing: old values take 150ms to flush
Result: Controller fights natural unwind for 150ms+
```

---

## Secondary Issue: Friction Compensation

**File:** `sunnypilot/selfdrive/controls/lib/latcontrol_torque_v0.py`

**Friction scaling (lines 29-30, 153-154):**
```python
# Line 29-30
FRICTION_X = [0.4, 0.6]   # m/s^2 desired lateral accel magnitude
FRICTION_Y = [1.5, 0.5]   # scale applied to friction input

# Line 153-154
desired_lataccel_mag = abs(future_desired_lateral_accel)
friction_error_scale = float(np.interp(desired_lataccel_mag, FRICTION_X, FRICTION_Y))
```

**Friction application (lines 149-158):**
```python
# Line 149-151
lane_change = bool(getattr(CS, "leftBlinker", False) or getattr(CS, "rightBlinker", False))
target_scale = 0.0 if lane_change else 1.0
friction_scale = float(self.friction_scale.update(target_scale))

# Line 155
friction_input = error * friction_error_scale

# Line 157-158
friction = get_friction(friction_input, lateral_accel_deadzone, FRICTION_THRESHOLD, self.torque_params)
ff += friction_scale * friction
```

**Problem:** Friction scales UP at low lateral acceleration (1.5x). During unwind (low lat accel), friction adds extra torque, fighting natural return-to-center.

---

## Tertiary Issue: LPF Smoothing

**File:** `opendbc_repo/opendbc/car/honda/carcontroller.py`

**LPF application (lines 251-261):**
```python
# Line 251-252
if self.override_state == "normal":
    # Normal operation: apply LPF smoothing at all speeds.
    
# Line 253
tau = 0.15
    
# Line 254
alpha = DT_CTRL / (tau + DT_CTRL)

# Line 259
self.torque_lpf = alpha * torque_cmd + (1.0 - alpha) * self.torque_lpf
```

**Problem:** Only 6.25% new value per frame (alpha = 0.01/0.16). Torque changes take ~400ms to settle.

---

## Summary of Delays

| Source | Location | Delay | Effect |
|--------|----------|-------|--------|
| Buffer read | latcontrol_torque_v0.py:129 | 150ms | Setpoint based on old values |
| Buffer clear | latcontrol_torque_v0.py:132 | 150ms | Old values persist in buffer |
| Friction scale | latcontrol_torque_v0.py:154 | 0ms | Adds torque during unwind |
| LPF | carcontroller.py:253,259 | ~400ms | Slow torque response |
| **Total** | | **~700ms+** | Slow unwind |

---

## Potential Fixes

1. **Predictive feedforward** - anticipate unwind and reduce torque
2. **Friction decay** - disable friction during low-speed unwind
3. **Reduce LPF tau** - faster torque response (carcontroller.py:253)
4. **Buffer bypass** - use current value during rapid transitions
5. **Steering angle rate** - detect unwind from wheel position
