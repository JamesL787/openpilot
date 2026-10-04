# Technical Reference: Honda Bosch ACC Internal Brake Command Pipeline

**Reverse Engineering Architecture from Wheel Speed & COM Ingestion to CAN 0x1DF Emission**

**Revision 2 — 2026-10-04**

> **Provenance.** Rebuilt as markdown from a browser-printed render of `honda_bosch_acc_brake_internals.md`
> (24-page PDF, sha256 `1f59c26eae913c17d219ab5b31d4960e57e8917205b1aa5249532254c18a1333`), with corrections from
> the cross-check `docs/xcheck_openpilot_2026-10-03.md` (PDF sha256
> `e18c49d2f9a13f2727c12729fae55e014c9175b8b86216809b931bcdd8d2ec7b`) and from the static re-decode in
> `tools/fw_acc_brake_pdf_check.py`. Neither PDF is committed.
>
> **Evidence status.** Every correction in this revision is **static**. Tags: [CONFIRMED static: PDF hex
> re-decode] = the PDF's own printed hex word re-decoded as PowerPC VLE disagrees with its printed text;
> [CONFIRMED static: opendbc DBC] = checked against the DBCs in this repo; [FIRMWARE TRACE by xcheck 2026-10-03,
> not re-run here] = the firmware image `36802TBA.dec.bin` and the xcheck scripts are **not in this repo**, so these
> items are carried from the cross-check and were not re-run. Nothing here is road-validated.
>
> **How to read this revision.** The original text is kept as printed. Each correction is a blockquote starting
> "Corrected 2026-10-04" placed after the passage it corrects; "see correction (x)" points to the full note, and the
> letters a-m are listed in the [Revision log](#revision-log). Sections 10-13 are new.

## 1. Executive Summary & System Overview

### 1.1 Purpose & Scope

This specification provides an exhaustive, assembly-level architectural reference of the stock Adaptive Cruise Control (ACC) and longitudinal braking pipeline implemented in the Bosch MRREVO14F radar firmware on the Honda "Bosch A" platform. It synthesizes findings from firmware disassembly ( `full.dis` , `full_hi.dis` ), binary tables ( `36802TBA.dec.bin` ), real-world vehicle CAN telemetry, and independent verification scripts.

The document reconstructs the complete signal path:

1. Four-wheel speed sensor ingestion over CAN message `0x1D0` ( `WHEEL_SPEEDS` ).
2. AUTOSAR COM longitudinal cruise demand extraction from signal `0x276` .

   > **Corrected 2026-10-04:** input b is **not** a radar/cruise "longitudinal demand"/"target"/"external demand".
   > COM 0x276 = `KINEMATICS` 0x094 `LONG_ACCEL`, the VSA's **measured** longitudinal acceleration (COM descriptor
   > `0x162604+12*h` → PDU 105 → CanIf tables → CAN 0x094) [FIRMWARE TRACE by xcheck 2026-10-03, not re-run here].
   > The firmware reads it as 10 bits, LSB 32 (MSB 25), unsigned, `raw*0.0478515625 - 24.5` (offset binary centred
   > at 512), then negates via `0x9c308`; opendbc has `LONG_ACCEL 24|9@0-` factor -0.049. For |value| < 256 counts
   > the low 9 bits of the offset-binary field equal the 9-bit two's complement, so both read the same; the scales
   > differ by 2.4% [CONFIRMED static: opendbc DBC]. So `0xd0c58` = **min(a, b) of two measured ego-acceleration
   > estimates** (wheel-speed derivative a, accelerometer b), clamped by `cfg[0x1c]`/`[0x18]`, fed to `G+0x6`. Old
   > "actual vs target" / "safety min-select against target deceleration" readings are withdrawn. What this bound
   > means for the rate limiter is an **open hypothesis**.

3. Upstream filtering, coordinate transformations, and numerical differentiation.
4. The core signed arbitration law at procedure `0xd0c58` ( $\min(a,b)$ ).
5. Downstream injection of an un-rate-limited upper ceiling into rate limiter `0x7c702` / `0x79c40` .
6. Mode 2 arbitration and gas/brake command formation at `0xea40e` .
7. Final serialization into CAN frame `0x1DF` ( `ACC_CONTROL` , 50 Hz).

### 1.2 The Bosch Longitudinal Architecture

On Honda Bosch A vehicles, the forward millimeter-wave radar mounted in the lower front grille acts as the **central autonomous cruise control, lead-vehicle tracking, and Automatic Emergency Braking (AEB) master ECU**.

Unlike camera-only or gateway-brokered systems:

- The radar directly ingests vehicle dynamics over Powertrain CAN (Bus 1), including individual wheel pulse speeds, steering angle, and yaw rate.
- The radar performs target detection, track association, kinematic trajectory prediction, and longitudinal acceleration demand planning within its internal RTOS.
- The radar acts as the sole bus master generating CAN message `0x1DF` ( `ACC_CONTROL` ), commanding the powertrain engine control module (ECM) and Vehicle Stability Assist (VSA/ABS) brake modulator directly.

### 1.3 High-Level Pipeline Architecture

The end-to-end signal flow from physical inputs to bus emission is shown below:

<!-- The diagram block renders EMPTY in the source PDF (page 2 shows an empty code box); its content is not recoverable from the PDF. -->
```text
```

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand.

### 1.4 Synthesis of Key Discoveries & Prior Errata Corrections

Early reverse engineering notes ( `acc_brake_notes.md` ) identified several critical memory structures but suffered from partial decompilation artifacts, coordinate system confusion, and incomplete downstream traces. This specification incorporates the authoritative corrections established in `audit_report.md` :

| Functional Subsystem | Historical Note Claim ( `acc_brake_notes.md` ) | Verified Ground Truth ( `audit_report.md` / Binary) | Technical Consequence |
|---|---|---|---|
| **Input $a$ Writer Routine** | "Function ending at `0x73128` " | Function spans `0x725d2` through `0x7332c` (3,418 bytes); `0x73128` is an internal load ( `e_lha r3, -0x1a(r29)` ). | Truncated 516 bytes of tracking state logic. |
| **Input $a$ Calibration Trim** | Trim factor omitted; labeled as direct speed derivative. | Formula: $a = \mathrm{sat}_{16}(Y + \mathrm{sat}_{16}((Y \times K) \gg 18))$ where $K = {*}(\mathtt{0x4001AA82})$. | $K$ is a signed 16-bit multiplicative calibration trim loaded via slot `-0x7c88(r13)` . |
| **Input $b$ Units** | "Likely 1/256 m/s²" | Calibration table `0x16661c` applies multiplier 2048.0; format is strictly **Q11** (1/2048 m/s²). | An 8 × engineering scale error was corrected. |
| **Input $b$ Record Offset** | Extracted from `0x40036A9C + 0x194` | `+0x194` stores two 8-bit status bytes; numerical demand resides at `+0x196` . | Field offset precision clarified. |
| **Input $b$ Filter Gating** | "Gated by status bit in `0x4001A9F4` " | Gate tests source byte `*(0x4001AA00 + 0x33)` bit 0. `0x4001A9F4` is destination flags ( `\|= 0xc0` ). | Inversion of source vs destination status registers resolved. |
| **`0xd0c58` Law Mechanics** | "Safety min-select against target deceleration" | Signed algebraic minimum $\min(a,b)$ on negated demand in signed acceleration space. | In signed space, $\min$ selects the **most negative acceleration** (strongest braking demand). |
| **Post-Min Clamping** | "Saturating against active brake limits" | Upper ceiling cap: $r3 \leftarrow \min(r3, \mathrm{cfg})$. | Clamping restricts how high acceleration can go; it does **not** enforce a lower brake deceleration floor. |
| **Downstream Role of `0xd0c58`** | Direct actuator command generator | Buffer relay `0xd0b6c` injects return value into rate limiter upper ceiling bound $G + \mathtt{0x6}$ ( `hi` ). | Un-rate-limited upper bound allows single-frame braking drops while rate limiter smooths steady-state tracking. |

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand. (Applies to the "Input $b$" rows and the "`0xd0c58` Law Mechanics" row above.)

## 2. Sensor Ingestion & Mathematical Foundations

### 2.1 Fixed-Point Engineering Units & Coordinate Systems

The Bosch MRREVO14F RTOS implements integer fixed-point arithmetic on its PowerPC VLE core to guarantee deterministic timing. Across the entire longitudinal tracking, lead solver, and arbitration pipeline, engineering dimensions obey strict fixed-point definitions:

| Physical Dimension | Representation | Format | Scale (1 LSB) | Full-Scale Dynamic Range | Canonical Memory Site |
|---|---|---|---|---|---|
| **Longitudinal Acceleration** | Signed 16-bit | **Q11** | $\frac{1}{2048}$ m/s² ≈ 0.00048828 m/s² | [−16.000, +15.9995] m/s² | `*(0x4003B144 + 0x18)` ( $a$ ), `*(0x4001A9F0 + 0x0)` ( $b$ ) |
| **Longitudinal Velocity** | Signed 16-bit | **Q8** | $\frac{1}{256}$ m/s ≈ 0.00390625 m/s | [−128.00, +127.996] m/s | `*(0x400492C4 + 0x4e + 2i)` ( $v_i$ ), `r29 - 0x16` ( $v_{\mathrm{ref}}$ ) |
| **Longitudinal Distance** | Signed 16-bit | **Q7** | $\frac{1}{128}$ m ≈ 0.0078125 m (7.81 mm) | [−256.00, +255.992] m | `L + 0x8` (Lead Gap), `0x4001AC50 + 0x14` ( $G + \mathtt{0x14}$ ) |
| **Discrete Loop Period** | Unsigned integer | Scalar | 41 counts ≈ 20.0195 ms | 41/2048 s | Task scheduler constant ( `0x9de36` , register `r9 = 0x29` ) |
| **CAN Wire Acceleration** | Signed 11-bit | Motorola | 0.01 m/s² | [−10.24, +10.23] m/s² | CAN `0x1DF` bit 31 ( `ACCEL_COMMAND` ) |

**Coordinate Polarity Invariant**

In ISO 8855 vehicle coordinate systems and throughout the Bosch firmware:

- $\mathbf{a > 0}$: Forward longitudinal propulsion (acceleration).
- $\mathbf{a < 0}$: Longitudinal deceleration / braking.
- A request for "stronger braking" corresponds strictly to an algebraically **more negative acceleration value**.

**Kinematic Scaling Invariant: $S_v^2 = 4 \cdot S_d \cdot S_a$**

The internal kinematic solvers (such as lead target solver `0x79804` ) compute stopping distance and constant-deceleration targets via Newtonian formulas ( $v^2 = 2ad$ ). For raw fixed-point quantities to evaluate without run-time rescaling:

$$S_v^2 = 4 \cdot S_d \cdot S_a \iff \left(\frac{1}{256}\right)^2 = 4 \cdot \left(\frac{1}{128}\right) \cdot \left(\frac{1}{2048}\right)$$

$$\frac{1}{65536} = \frac{4}{262144} = \frac{1}{65536} \quad \text{[Exact Identity]}$$

This mathematical identity binds the Q8 speed, Q7 distance, and Q11 acceleration scales together into an internally consistent kinematic framework.

### 2.2 Wheel Speed Ingestion Pipeline (CAN `0x1D0` to Struct `S` )

The vehicle speed reference originates in the Vehicle Stability Assist (VSA/ABS) module, which broadcasts raw wheel pulse counts over Powertrain CAN via message `0x1D0` ( `WHEEL_SPEEDS` , 50 Hz).

```text
CAN 0x1D0 (WHEEL_SPEEDS, 50 Hz)
  ├── FL: Start bit 9,  Length 15, Motorola -> COM Signal 0x2b9
  ├── FR: Start bit 26, Length 15, Motorola -> COM Signal 0x2b8
  ├── RL: Start bit 43, Length 15, Motorola -> COM Signal 0x2b7
  └── RR: Start bit 60, Length 15, Motorola -> COM Signal 0x2b6
```

> **Corrected 2026-10-04 (confirmation):** COM 0x2b6..0x2b9 = CAN 0x1D0 `WHEEL_SPEEDS` confirmed: PDU 110, all 4
> signals match opendbc; readers at 0x144988..0x144a04 [FIRMWARE TRACE by xcheck 2026-10-03, not re-run here;
> DBC side CONFIRMED static: opendbc DBC].

1. **AUTOSAR COM Unpacking ( `0x136edc` / `0x1373ba` )**

   All four wheel speed signals belong to AUTOSAR COM PDU configuration entry #110. Ingestion function `0x14a6c4` retrieves the unpacked 15-bit unsigned raw values (0.01 km/h per count) from receive shadow buffer `0x40017398 + 2 * d.u16[4]` .

2. **Linear Transformation to Q8 Format ( `0x144974` / `0x11f3dc` )**

   At `0x144974` , for each wheel index $i \in \{0, 1, 2, 3\}$, subroutine `0x11f3dc` applies linear conversion table `0x11f302` :
   Parameters: $[t_0 = 0.01, \quad t_1 = 0.0, \quad t_2 = 256.0, \quad t_3 = 0.27777778\ (1/3.6)]$
   $v_i = \mathrm{sat}_{16}\left(\mathrm{round}\left(\mathrm{raw}_i \times 0.01 \times \frac{1}{3.6} \times 256.0\right)\right)$
   This transforms speed in km/h directly into **signed 16-bit Q8 velocity** (1 LSB = 1/256 m/s). For example, 36.00 km/h = 10.00 m/s = 2,560 counts.

3. **Storage in Intermediate Struct `0x40036A9C`**

   The converted records are written to array `0x40036A9C + 0x28a + 4i` :

   - Byte 0: Validity byte $b_0 = 1$
   - Byte 1: Status byte $b_1 = 1$
   - Bytes 2–3: Signed 16-bit velocity $v_i$ (Q8 format)

4. **Directional Orientation via Gear Flag ( `0xbc960` / `0xbcdf8` )**

   Reader routine `0xbc960` / `0xbca4a` verifies status validity and transfers values to structure `S` ( `0x400492C4 + 0x4e + 2i` ). At `0xbcdf8` , directional conditioning is applied using the gear orientation flag loaded from Small Data Area (SDA) byte `r13 - 0x3eee` :

   - `+1` : Forward driving gears (D, S, 1..6)
   - `-1` : Reverse gear (R; evaluated when transmission float `r31 + 0x48 < -0.8` ) $W_i = v_i \times \mathrm{direction\_flag}$ Conditioned wheel speeds are stored into Structure `D` ( `0x4001AA00` ), with calibrated wheel speeds published to SDA globals `r13 - 0x5388` through `-0x5382` and array `0x4001A368` .. `0x4001A36E` .

### 2.3 Radar Cruise Demand Ingestion (COM Signal `0x276` to Struct `0x40036A9C` )

The radar's cruise tracking supervisor receives longitudinal acceleration demand commands via AUTOSAR COM signal `0x276` .

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand.

1. **Ingestion & Companion Signal Validation ( `0x143630` – `0x14366e` )**

   In upper flash ( `full_hi.dis:65511` – `65538` ):

   ```assembly
   0x143630  516d8c78  e_lwz r11, -0x7388(r13)      # r11 = 0x40036A9C (Record Base)
   0x143642  70600276  e_li r3, 0x276               # r3 = 0x276 (Signal Handle ID: Longitudinal Demand)
   0x143654  78007071  e_bl 0x14a6c4                # Com_ReceiveSignal(0x276, &stack[0x1a])
   0x143658  70600274  e_li r3, 0x274               # r3 = 0x274 (Signal Handle ID: Companion Validity)
   0x14365c  18818009  e_addi r4, r1, 0x9           # r4 = &stack[0x9]
   0x143660  78007065  e_bl 0x14a6c4                # Com_ReceiveSignal(0x274, &stack[0x9])
   0x143664  31610009  e_lbz r11, 0x9(r1)           # r11 = companion validity flag
   0x143668  180ba801  e_cmpi cr0, r11, 0x1         # Assert companion == 1 (Valid)
   0x14366c  e203      se_bne 0x143672              # If valid, branch forward
   0x14366e  1bbdc600  e_andi r29, r29, 0xff00ffff  # If invalid, clear status byte 1
   ```

   > **Corrected 2026-10-04:** 0x274 is a 1-bit field at LSB 52 of 0x094; opendbc has no signal there, so
   > "companion validity" is **unproven** [FIRMWARE TRACE by xcheck 2026-10-03, not re-run here]. The branch at
   > `0x14366c e203` (`se_bne` → 0x143672) **skips** the `e_andi` at 0x14366e when the byte != 1, so the clear runs
   > when the byte **== 1** — the opposite of the original comment [CONFIRMED static: PDF hex re-decode].

2. **Calibration Table `0x16661c` & Q11 Conversion ( `0x143672` – `0x143682` )**

   At ROM address `0x16661c` (file offset `0x13661c` in `36802TBA.dec.bin` ), four single-precision IEEE-754 floats define the linear calibration transfer function:

   $$\text{Table at } \mathtt{0x16661c} = \begin{bmatrix} t_0 = 0.0478515625 \\ t_1 = -24.5 \\ t_2 = 2048.0 \\ t_3 = 1.0 \end{bmatrix}$$

   Subroutine `0x11f302` applies the transformation: $y = (((raw \times t_0) + t_1) \times t_3) \times t_2$

   $$y = ((raw \times 0.0478515625 - 24.5) \times 1.0) \times 2048.0 = raw \times 98.0 - 50176.0$$

   The multiplier $t_2 = 2048.0 = 2^{11}$ establishes the internal **signed 16-bit Q11 format** (1 LSB = 1/2048 m/s²). Subroutine `0x11f3dc` rounds $y$ and saturates the result into $[-32768, +32767]$ counts.

3. **Intermediate Storage**

   At `0x14369c` and `0x1436a4` :

   - `*(0x40036A9C + 0x194)` : Stores 16 bits of status flags (status byte 0 and status byte 1).
   - `*(0x40036A9C + 0x196)` : Stores the calibrated signed 16-bit demand in Q11 counts.

## 3. Deep-Dive: Upstream Provenance of Ego Acceleration ( `a` )

Input $a$ to procedure `0xd0c58` is **Filtered Ego Longitudinal Acceleration** ( `*(0x4003B144 + 0x18)` ). It is derived purely from wheel speed sensor differentiation and filtering, disproving assumptions of an onboard IMU accelerometer origin.

```text
Four Wheel Speeds (CAN 0x1D0)
  │
  ▼ [0x725d2..728f2] Geometry & Yaw Corrections
Midrange Speed: trunc((max + min) / 2)
  │
  ▼ [0x72d18..72d4e] 5-Tap FIR Moving Average (Reciprocal 0x66666667)
Longitudinal Reference Speed v_ref (Q8, 1/256 m/s) @ -0x16(r29)
  │
  ▼ [0x72d54..72d64] Finite Difference + Saturated Differentiator (dt = 41 / 2048 s)
Raw Acceleration Derivative: Y_dot_raw = sat16((Delta Y << 14) / 41) (Q11, 1/2048 m/s²)
  │
  ▼ [0x72d96..72ea4] Dual Cascaded 1st-Order IIR Low-Pass Filters (Coeffs 0xa4, 0x333)
Filtered Ego Acceleration: Y @ -0xa(r29) (0x4001A458 - 0xa)
  │
  ▼ [0x730e4..73104] Multiplicative Calibration Trim: a = sat16(Y + sat16((Y * K) >> 18))
Committed to Struct A: *(0x4003B144 + 0x18)
```

### 3.1 Structural Source & Memory Base

Structure `A` resides at base address `0x4003B144` . It is aliased across two Small Data Area slots:

1. **Producer Slot `-0x7c70(r13)`** : Initialized at `0x76816` – `0x76836` via `0x40040000 - 0x4ebc = 0x4003B144` .
2. **Consumer Slot `-0x7588(r13)`** : Initialized at `0xc4eae` – `0xc4eca` via `0x40040000 - 0x4ebc = 0x4003B144` .

Both slots reference the identical physical address: $\mathrm{Address}(a) = \mathtt{0x4003B144} + \mathtt{0x18} = \mathtt{0x4003B15C}$

### 3.2 Reference Speed Estimation & 5-Sample Moving Average

Primary tracking function `0x725d2` executes periodically at 50 Hz.

- **Base Pointer**: Frame pointer `r29` is established at `0x725e0` :
  $r29 = r13 - \mathtt{0x5298} = \mathtt{0x4001F6F0} - \mathtt{0x5298} = \mathtt{0x4001A458}$
- **Geometry & Outlier Filtering ( `0x727d6` – `0x728f2` )**: Yaw rate and steering angle corrections compensate for inner/outer wheel radius variations during cornering. Outliers are rejected, and the midrange reference is computed:
  $v_{\mathrm{mid}} = \mathrm{trunc}\left(\frac{\max(W_{\mathrm{valid}}) + \min(W_{\mathrm{valid}})}{2}\right)$
- **5-Tap Moving Average ( `0x72d18` – `0x72d4e` )**: Historical samples are buffered at `r29[-0x3c + 2i]` . The sum $S_v = \sum_{i=0}^{4} v[t-i]$ is divided by 5 using reciprocal multiplication via constant `0x66666667` :

  ```assembly
  0x72d38  710ce666  e_lis r8, 0x6666
  0x72d3c  1d086667  e_add16i r8, r8, 0x6667     # r8 = 0x66666667
  0x72d40  7d880096  mulhw r12, r8, r0           # r12 = (0x66666667 * S_v) >> 32
  0x72d44  6bf0      se_srawi r0, 0x1f           # r0 = sign_bit(S_v) (0 or -1)
  0x72d46  7d8c0e70  srawi r12, r12, 1           # r12 = r12 >> 1
  0x72d4a  7d806050  subf r12, r0, r12           # r12 = (r12 >> 1) - sign = trunc(S_v / 5)
  0x72d4e  5c6dffe8  e_sth r3, -0x16(r29)        # Store v_ref at -0x16(r29) (1/256 m/s)
  ```

  > **Corrected 2026-10-04:** `0x72d4e 5c6dffe8` decodes as `e_sth r3,-0x18(r13)`, not `-0x16(r29)`; and the /5
  > quotient is in r12. The v_ref store claim is **not supported by its own hex** [CONFIRMED static: PDF hex re-decode].

### 3.3 Numerical Differentiation ( $\Delta Y / \Delta t$ )

The conversion from vehicle speed (1/256 m/s) to acceleration (1/2048 m/s²) is executed at `0x72d54` – `0x72d64` :

1. **Finite Speed Difference ( `0x72d54` )**: Calls subroutine `0x9c1ce` ( `sat16(r3 - r4)` ):
   $\Delta Y = v_{\mathrm{ref}}[t] - v_{\mathrm{ref}}[t-1] \quad \text{(counts of 1/256 m/s)}$
2. **Loop Period Acquisition ( `0x72d5a` )**: Helper `0x9de36` loads discrete timer constant $dt = 41$ (hex `0x29`) counts: $\Delta t = \frac{41}{2048}\ \mathrm{s} \approx 0.0200195\ \mathrm{s} \quad \text{(20.02 ms)}$
3. **Saturated Differentiation Helper `0x9b320` ( `0x72d64` )**: Computes raw numerical acceleration:
   $\dot{Y}_{\mathrm{raw}} = \mathrm{sat}_{16}\left(\frac{\Delta Y \ll 14}{41}\right) = \mathrm{sat}_{16}\left(\frac{\Delta Y \times 16384}{41}\right)$

**Exact Mathematical Derivation of the Scale Transformation**

$$\Delta v_{\mathrm{phys}} = \Delta Y \times \frac{1}{256}\ \mathrm{m/s}, \quad \Delta t_{\mathrm{phys}} = \frac{41}{2048}\ \mathrm{s}$$

$$a_{\mathrm{phys}} = \frac{\Delta v_{\mathrm{phys}}}{\Delta t_{\mathrm{phys}}} = \frac{\Delta Y / 256}{41/2048} = \frac{\Delta Y \times 2048}{256 \times 41} = \frac{\Delta Y \times 8}{41}\ \mathrm{m/s^2}$$

To represent $a_{\mathrm{phys}}$ in fixed-point Q11 counts (1 LSB = 1/2048 m/s²):

$$\mathrm{Counts}_{\mathrm{accel}} = a_{\mathrm{phys}} \times 2048 = \left(\frac{\Delta Y \times 8}{41}\right) \times 2048 = \frac{\Delta Y \times 16384}{41} = \frac{\Delta Y \ll 14}{41} \quad \textbf{[Q.E.D.]}$$

### 3.4 Dual Cascaded First-Order IIR Low-Pass Filtering

To suppress pulse quantization chatter, $\dot{Y}_{\mathrm{raw}}$ passes through two cascaded first-order IIR low-pass filter stages between `0x72d96` and `0x72ea4` :

- Filter state halfwords relative to `r29` ( `0x4001A458` ):
  - `r29 - 0x12` : First-stage accumulator state
  - `r29 - 0x10` : Second-stage intermediate state
  - `r29 - 0xe` : Final filtered accumulator output
  - `r29 - 0xa` : Exported filtered acceleration $Y$
- Filter coefficients: loaded from `0x72c52` ( $\alpha_1 = \mathtt{0x00a4} = 164$ ) and `0x72d9e` ( $\alpha_2 = \mathtt{0x0333} = 819$ ).
- Discrete recurrence equation: $y_k = y_{k-1} + \mathrm{sat}_{16}\left(\frac{\alpha \times (x_k - y_{k-1})}{2^{16}}\right)$ At `0x72ea0` – `0x72ea4` :

```assembly
0x72ea0  587dfff2  e_lhz r3, -0xe(r29)   # Load final IIR state
0x72ea4  5c7dfff6  e_sth r3, -0xa(r29)   # Commit to -0xa(r29) (0x4001A458 - 0xa)
```

Variable $Y = {*}(\mathtt{0x4001A458} - \mathtt{0xa})$ represents the **filtered ego longitudinal acceleration** in Q11 format.

> **Corrected 2026-10-04:** alphas 164/2^16 and 819/2^16 give time constants of **~8.0 s and ~1.6 s** at 20 ms
> steps, and with truncation |x−y| < 400 (stage 1) / 80 (stage 2) Q11 counts produce no state change. This is
> **implausible for a brake path; needs re-trace** [CONFIRMED static: arithmetic on the printed constants].

### 3.5 Calibration Trim & Commit Routine ( `0x725d2` – `0x7332c` )

At lines `0x730e4` – `0x73104` :

```assembly
0x730e4  516d8378  e_lwz r11, -0x7c88(r13)   # r11 = 0x4001AA80
0x730e8  387dfff6  e_lha r3,  -0xa(r29)      # r3  = Y = *(0x4001A458 - 0xa)
0x730ec  388b0002  e_lha r4,  0x2(r11)       # r4  = K = *(0x4001AA82)
0x730f0  4925      se_li r5,  0x12           # r5  = 18 (shift right 18)
0x730f2  7802910f  e_bl 0x9c200              # r3  = sat16((Y * K) >> 18)
0x730f6  0134      se_mr r4,  r3             # r4  = trim term
0x730f8  387dfff6  e_lha r3,  -0xa(r29)      # r3  = Y reloaded
0x730fc  780290a7  e_bl 0x9c1a2              # r3  = sat16(Y + r4)
0x73100  518d8390  e_lwz r12, -0x7c70(r13)   # r12 = 0x4003B144 (Struct A)
0x73104  5c6c0018  e_sth r3,  0x18(r12)      # *(0x4003B144 + 0x18) = a (WRITE TO a)
```

**Mathematical Formulation**

$$a = \mathrm{sat}_{16}\left(Y + \mathrm{sat}_{16}\left(\frac{Y \times K}{2^{18}}\right)\right) = \mathrm{sat}_{16}\left(Y \times \left(1 + \frac{K}{262144}\right)\right)$$

Where:

- $Y = {*}(\mathtt{0x4001A458} - \mathtt{0xa})$ is filtered ego acceleration in Q11 counts.
- $K = {*}(\mathtt{0x4001AA82})$ is a signed 16-bit calibration parameter loaded via slot `-0x7c88(r13)` ( `0x4001AA80 + 0x2` ).
- Parameter $K$ provides a pure fractional multiplicative gain adjustment (1 count ≈ +0.000381%) with zero additive bias.

**Verification of Function Boundaries**

- **Entry ( `0x725d2` )**: `e_stwu r1, -0x70(r1)` allocates 112 bytes of stack; preserves non-volatile registers `r14` – `r31` via `e_stmw r14, 0x28(r1)` .
- **Instruction at `0x73128`** : `387dffe6 e_lha r3, -0x1a(r29)` is an internal local load instruction continuing tracking calculations.
- **Exit ( `0x7332c` )**: Restores registers `e_lmw r14, 0x28(r1)` , restores link register `se_mtlr r0` , deallocates stack `e_addi r1, r1, 0x70` , and returns via `se_blr` . Total function length: **3,418 bytes**.

## 4. Deep-Dive: Upstream Provenance of Radar Demand ( `b` )

Input $b$ to procedure `0xd0c58` is **Filtered Negated Radar Demand** ( `*(0x4001A9F0 + 0x0)` ). It originates from AUTOSAR COM signal `0x276` , undergoing linear conversion, saturating negation, and a 5-tap moving average FIR filter.

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand.

```text
AUTOSAR COM Signal 0x276 (Companion 0x274 Validated)
  │
  ▼ [0x143672..82] Table 0x16661c Float Transform: raw * 98.0 - 50176.0
Scaled Demand @ *(0x40036A9C + 0x196) (Q11, 1/2048 m/s²)
  │
  ▼ [0xbc5c6..bc5f2] Status Check + Saturating Negation (0x9c308)
Negated Demand: -(COM_Demand) @ *(0x4001AA00 + 0x12) (Q11)
  │
  ▼ [0x7095a..7099c] Status Gate Check (*(0x4001AA00 + 0x33) b0)
5-Sample FIR Boxcar Filter (0x7090a, Reciprocal Divisor 0x66666667)
  │
  ▼ [0x7099c] Commit Store via Slot -0x7c74(r13)
Input b @ *(0x4001A9F0 + 0x0) (Q11, 1/2048 m/s²)
```

### 4.1 Structural Source & Memory Base

Structure `B` resides at base address `0x4001A9F0` . It is aliased across:

1. **Producer Slot `-0x7c74(r13)`** : Initialized at `0x767a8` via `0x4001F6F0 - 0x4d00 = 0x4001A9F0` .
2. **Consumer Slot `-0x7598(r13)`** : Initialized at `0xc4ed6` via `0x4001F6F0 - 0x4d00 = 0x4001A9F0` .

The field resides at offset `+0x0` : $\mathrm{Address}(b) = \mathtt{0x4001A9F0} + \mathtt{0x0} = \mathtt{0x4001A9F0}$

### 4.2 Ingestion, Status Checks & Saturating Negation ( `0xbc570` – `0xbc618` )

In middle flash ( `full.dis:165780` – `165806` ):

```assembly
0xbc5c6  50cd8994  e_lwz r6, -0x766c(r13)     # r6 = 0x40036A9C
0xbc5ca  58e60194  e_lhz r7, 0x194(r6)        # r7 = Status bytes 0 and 1
0xbc5d2  58e60196  e_lhz r7, 0x196(r6)        # r7 = Scaled demand value (int16)
0xbc5da  5061009c  e_lwz r3, 0x9c(r1)         # r3 = [status0 : status1 : demand]
0xbc5de  7c68c471  e_srwi. r8, r3, 0x18       # Status byte 0 must be non-zero
0xbc5e2  e610      se_beq 0xbc602             # Branch on failure
0xbc5e4  7469863f  e_rlwinm r9, r3, 0x10, 0x18, 0x1f # Extract status byte 1
0xbc5e8  1809a801  e_cmpi cr0, r9, 0x1        # Assert status byte 1 == 1
0xbc5ee  e213      se_bne 0xbc614             # Branch on invalid status
0xbc5f0  00f3      se_extsh r3                # Sign-extend 16-bit demand
0xbc5f2  79fdfd17  e_bl 0x9c308               # CALL SATURATING NEGATION ROUTINE
0xbc5f6  514d89a0  e_lwz r10, -0x7660(r13)    # r10 = 0x4001AA00 (Struct D)
0xbc5fa  4835      se_li r5, 0x3              # r5 = 3 (Valid status; bit 0 = 1)
0xbc5fc  5c6a0012  e_sth r3, 0x12(r10)        # *(0x4001AA00 + 0x12) = r3 (STORE TO 0x4001AA12)
0xbc614  50cd89a0  e_lwz r6, -0x7660(r13)     # r6 = 0x4001AA00
0xbc618  34a60033  e_stb r5, 0x33(r6)         # *(0x4001AA00 + 0x33) = r5 (Sets bit 0)
```

**Helper Routine `0x9c308` : Saturating Negation**

Subroutine `0x9c308` ( `full.dis:107412` – `107419` ) implements two's complement negation with boundary saturation:

```assembly
0x9c308  0130      se_mr r0, r3               # r0 = input r3
0x9c30a  72039800  e_cmp16i. r3, -0x8000      # Compare with -32768
0x9c30e  2cf3      se_bmaski r3, 0xf          # Preload r3 = 0x7FFF (+32767)
0x9c310  e604      se_beq 0x9c318            # If input == -32768, return saturated +32767
0x9c312  7c6000d0  neg r3, r0                 # r3 = -r0 (Two's complement negation)
0x9c316  00f3      se_extsh r3                # Sign-extend 16 bits
0x9c318  0004      se_blr                     # Return
```

$$\mathrm{neg\_sat}_{16}(x) = \begin{cases} +32767 & \text{if } x = -32768 \\ -x & \text{if } x \in [-32767, +32767] \end{cases}$$

Negation maps incoming deceleration requests into signed negative numbers ( $b < 0$ ), aligning them with the coordinate frame of Ego Acceleration $a$.

### 4.3 Gating & 5-Sample Moving Average Filter ( `0x7095a` – `0x7099c` )

Routine `0x7095a` consumes `*(0x4001AA00 + 0x12)` and outputs `b` :

```assembly
0x7095a  182106d0  e_stwu r1, -0x30(r1)       # Allocate stack
0x70966  50ed8368  e_lwz r7, -0x7c98(r13)     # r7 = 0x4001AA00 (Struct D)
0x7096a  50ad838c  e_lwz r5, -0x7c74(r13)     # r5 = 0x4001A9F0 (Struct B)
0x7096e  31070033  e_lbz r8, 0x33(r7)         # r8 = *(0x4001AA00 + 0x33) (Source Status)
0x70972  1909c801  e_andi. r8, r9, 0x1        # Test bit 0 of source status byte
0x70976  8405      se_lbz r0, 0x4(r5)         # r0 = *(0x4001A9F0 + 0x4) (Destination Flags)
0x70978  e60b      se_beq 0x7098e            # If bit 0 == 0 (invalid), branch to fallback
# --- Valid External Demand Path ---
0x7097a  180ad0c0  e_ori r0, r10, 0xc0        # Assert flags 0xc0 (bits 6 and 7)
0x7097e  35450004  e_stb r10, 0x4(r5)         # Update *(0x4001A9F0 + 0x4) |= 0xc0
0x70982  518d8368  e_lwz r12, -0x7c98(r13)    # r12 = 0x4001AA00
0x70986  386c0012  e_lha r3, 0x12(r12)        # r3 = *(0x4001AA00 + 0x12) (Negated Demand)
0x7098a  e9c0      se_bl 0x7090a             # Call 5-sample moving average filter
0x7098c  e806      se_b 0x70998              # Branch to commit
# --- Fallback Path (Invalid Input) ---
0x7098e  1800c43f  e_andi r0, r0, 0xffffff3f  # Clear flags 0xc0: r0 &= ~0xc0
0x70992  4803      se_li r3, 0x0              # Feed 0 into filter
0x70994  9405      se_stb r0, 0x4(r5)         # Update *(0x4001A9F0 + 0x4) &= ~0xc0
0x70996  e9ba      se_bl 0x7090a             # Call filter on 0
# --- Final Commit Store ---
0x70998  510d838c  e_lwz r8, -0x7c74(r13)     # r8 = 0x4001A9F0
0x7099c  5c680000  e_sth r3, 0x0(r8)          # *(0x4001A9F0 + 0x0) = r3 (WRITE TO b)
```

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand.

> **Corrected 2026-10-04 (cosmetic):** operand order of `1909c801` / `180ad0c0` is reversed in the printed
> mnemonic [CONFIRMED static: PDF hex re-decode].

**5-Sample Moving Average Filter ( `0x7090a` – `0x70958` )**

Subroutine `0x7090a` maintains a 4-sample delay line buffer at `r13 - 0x53b0` ( `0x4001A340` ):

- Initializes accumulator $r0 = \mathrm{new\_sample}$.
- Loops 3 times shifting delay buffer elements ( `buffer[3] <- buffer[2] <- buffer[1] <- buffer[0]` ) and summing all samples into $r0$.
- Loads `buffer[0]` and computes 5-sample sum $S = \mathrm{new} + \sum_{i=0}^{3} \mathrm{old}_i$.
- Executes signed division by 5 using reciprocal constant $M = \mathtt{0x66666667} = \lfloor 2^{33}/5 \rfloor + 1 = 1{,}717{,}986{,}919$:

  ```assembly
  0x70936  710ce666  e_lis r8, 0x6666
  0x7093a  1d086667  e_add16i r8, r8, 0x6667    # r8 = 0x66666667
  0x7093e  7c005214  add r0, r0, r10           # r0 = S
  0x70942  7d880096  mulhw r12, r8, r0         # r12 = high 32 bits of (0x66666667 * S)
  0x70946  6bf0      se_srawi r0, 0x1f         # r0 = sign_bit(S) (0 or -1)
  0x70948  7d8c0e70  srawi r12, r12, 0x1       # r12 = r12 >> 1
  0x7094c  7d806050  subf r12, r0, r12         # r12 = (r12 >> 1) - sign = trunc(S / 5)
  0x70950  5c6dac50  e_sth r3, -0x53b0(r13)    # buffer[0] = new_sample
  0x70954  7d830734  extsh r3, r12            # Sign-extend 16 bits
  ```

The truncated integer quotient is stored at `0x7099c` to `*(0x4001A9F0 + 0x0) = b` .

## 5. The `0xd0c58` Brake Arbitration Law

Procedure `0xd0c58` is an 88-byte leaf method in the Bosch firmware executing the core arbitration law between Ego Acceleration $a$ and Radar Demand $b$.

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand.

```text
0xd0c58 Arbitration Flow:
  r10 = a = *(0x4003B144 + 0x18)  [Ego Accel, Q11]
  r0  = b = *(0x4001A9F0 + 0x0)   [Radar Demand, Q11]
         │
         ▼
  cmpw cr0, r10, r0
  isellt r3, r10, r0, cr0   ──>  r3 = min(a, b) (Signed algebraic min)
         │
         ├─── if cfg[0] in {1, 2}:  r3 = min(r3, cfg[0x1c])  (Upper Ceiling Cap 1)
         │
         ├─── elif cfg[3] in {1, 2}: r3 = min(r3, cfg[0x18])  (Upper Ceiling Cap 2)
         │
         └─── else: return r3 unclamped
```

### 5.1 Object-Oriented Calling Context

- **Virtual Method Table**: `0xd0c58` occupies slot `+0x7c` of Class B vtable `0x15d808` ( `0x160000 - 0x27f8` ).
- **Caller ( `0xdb56c` )**: Invoked periodically via CTR indirect branch at `0xdb582` , storing its return value into static Class B instance `0x400497F8` :

  ```assembly
  0xdb576  51830004  e_lwz r12, 0x4(r3)        # r12 = vptr (0x15d808)
  0xdb57a  500c007c  e_lwz r0,  0x7c(r12)       # r0 = vtable[+0x7c] = 0xd0c58
  0xdb57e  00b0      se_mtctr r0               # Set Count Register
  0xdb580  013f      se_mr r31, r3             # r31 = this instance (0x400497F8)
  0xdb582  0007      se_bctrl                  # Call 0xd0c58
  0xdb584  5c7f0070  e_sth r3,  0x70(r31)       # obj+0x70 = r3 (STORE TO obj+0x70)
  ```

### 5.2 Verbatim Assembly Disassembly & Instruction Breakdown

From `dis/full.dis` (lines 192229–192254):

```assembly
0xd0c58  514d8a78  e_lwz r10, -0x7588(r13)     # r10 = 0x4003B144 (Struct A Pointer)
0xd0c5c  512d8a68  e_lwz r9,  -0x7598(r13)     # r9  = 0x4001A9F0 (Struct B Pointer)
0xd0c60  518d8adc  e_lwz r12, -0x7524(r13)     # r12 = 0x4001AD08 (Config Struct M)
0xd0c64  394a0018  e_lha r10, 0x18(r10)        # r10 = a = s16 *(0x4003B144 + 0x18)
0xd0c68  38090000  e_lha r0,  0x0(r9)          # r0  = b = s16 *(0x4001A9F0 + 0x0)
0xd0c6c  316c0000  e_lbz r11, 0x0(r12)         # r11 = uint8 cfg[0] (Mode byte 0)
0xd0c70  312c0003  e_lbz r9,  0x3(r12)         # r9  = uint8 cfg[3] (Mode byte 3)
0xd0c74  7c0a0000  cmpw cr0, r10, r0           # Signed compare: r10 (a) vs r0 (b)
0xd0c78  7c6a001e  isellt r3, r10, r0, cr0     # r3 = (a < b) ? a : b  [Signed min(a, b)]
0xd0c7c  180ba801  e_cmpi cr0, r11, 0x1        # Test cfg[0] == 1
0xd0c80  00f3      se_extsh r3                 # Sign-extend r3
0xd0c82  e604      se_beq 0xd0c8a             # If cfg[0] == 1, jump to Clamp 1
0xd0c84  180ba802  e_cmpi cr0, r11, 0x2        # Test cfg[0] == 2
0xd0c88  e208      se_bne 0xd0c98             # If cfg[0] != 2, jump to test cfg[3]
0xd0c8a  394c001c  e_lha r10, 0x1c(r12)        # r10 = s16 cfg[0x1c] (Calibrated ceiling 1)
0xd0c8e  7c0a1800  cmpw cr0, r10, r3           # Signed compare: cfg[0x1c] vs r3
0xd0c92  7c6a181e  isellt r3, r10, r3, cr0     # r3 = (cfg[0x1c] < r3) ? cfg[0x1c] : r3
0xd0c96  0004      se_blr                     # Return min(r3, cfg[0x1c])
0xd0c98  1809a801  e_cmpi cr0, r9, 0x1         # Test cfg[3] == 1
0xd0c9c  e604      se_beq 0xd0ca4             # If cfg[3] == 1, jump to Clamp 2
0xd0c9e  1809a802  e_cmpi cr0, r9, 0x2         # Test cfg[3] == 2
0xd0ca2  e207      se_bne 0xd0cb0             # If cfg[3] != 2, return unclamped r3
0xd0ca4  394c0018  e_lha r10, 0x18(r12)        # r10 = s16 cfg[0x18] (Calibrated ceiling 2)
0xd0ca8  7c0a1800  cmpw cr0, r10, r3           # Signed compare: cfg[0x18] vs r3
0xd0cac  7c6a181e  isellt r3, r10, r3, cr0     # r3 = (cfg[0x18] < r3) ? cfg[0x18] : r3
0xd0cb0  0004      se_blr                     # Return min(r3, cfg[0x18])
```

> **Corrected 2026-10-04:** the `0xd0c58` body is **90 bytes (0x5a)**, not 88. The min(a, b) law itself decodes
> exactly as printed [CONFIRMED static: PDF hex re-decode].

### 5.3 Mathematical Proof of Signed Minimum in Coordinate Space

At lines `0xd0c74` – `0xd0c78` :

```assembly
cmpw cr0, r10, r0
isellt r3, r10, r0, cr0
```

In PowerPC VLE, `isellt rD, rA, rB, cr0` selects register `rA` if condition register field `cr0` indicates "Less Than" in signed two's complement arithmetic; otherwise it selects `rB` : $r3 = \min_{\mathrm{signed}}(a, b)$

**Resolution of the Deceleration Selection Paradox**

In early notes, this operation was described as a "safety min-select against target deceleration". However:

1. In a positive-deceleration coordinate system ( $D \ge 0$ ), computing $\min(D_{\mathrm{ego}}, D_{\mathrm{target}})$ would select the **smaller deceleration** (weaker braking). For instance, $\min(1.0, 3.0) = 1.0\ \mathrm{m/s^2}$, which would fail to brake sufficiently in a collision emergency!
2. In the Bosch firmware, all acceleration quantities are signed:
   - Positive acceleration ( $> 0$ ): forward propulsion.
   - Negative acceleration ( $< 0$ ): deceleration / braking.
3. External demand COM 0x276 was explicitly negated by helper `0x9c308` at `0xbc5f2`: $b = -\text{COM\_Demand}$ Thus, an external cruise request for $2.5\ \mathrm{m/s^2}$ deceleration enters arbitration as $b = -2.5 \times 2048 = -5{,}120$ counts.
4. In signed two's complement arithmetic: $-5120 < -1024 \longrightarrow \min(-1024, -5120) = -5120$ The algebraically smaller value is the **more negative number**, representing the **strongest deceleration / greatest braking effort**.
5. **Operational Behavior**:
    - **Case 1 (Cruise demands braking, vehicle cruising)**: $a = +0.5\ \text{m/s}^2$ (+1024), $b = -2.0\ \text{m/s}^2$ (−4096). $\min(a,b) = -4096$ ($-2.0\ \text{m/s}^2$). The braking demand overrides cruising.
    - **Case 2 (Driver or grade causes steep vehicle deceleration)**: $a = -3.5\ \text{m/s}^2$ (−7168), $b = -1.0\ \text{m/s}^2$ (−2048). $\min(a,b) = -7168$ ($-3.5\ \text{m/s}^2$). The system selects the vehicle's actual heavier deceleration, preventing the rate limiter from fighting the ongoing deceleration event.

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand.

### 5.4 Post-Min Status-Gated Upper Ceiling Clamping

Following the initial $\min(a,b)$ selection, lines `0xd0c7c` – `0xd0cb0` evaluate active configuration structure `M` (`0x4001AD08`, loaded via slot `-0x7524(r13)`):

- If $\text{cfg}[0] \in \{1,2\}$: $r3 \leftarrow \min(r3, \text{cfg}[0x1c])$
- Else if $\text{cfg}[3] \in \{1,2\}$: $r3 \leftarrow \min(r3, \text{cfg}[0x18])$
- Otherwise: $r3$ returns unmodified.

#### Architectural Proof: Upper Ceiling Cap vs. Lower Floor Saturation

A common engineering misconception is labeling this clamping as "brake saturation".

- A **lower saturation floor** (maximum braking limit) bounds deceleration from below:
  $y = \max(x, \text{limit}_{\text{floor}})$ (implemented via `iselgt`)
- The instruction at `0xd0c92` and `0xd0cac` is `isellt r3, r10, r3, cr0` where `r10` holds the configuration parameter:
  $r3 = (\text{cfg} < r3)\ ?\ \text{cfg} : r3 \iff r3 \leftarrow \min(r3, \text{cfg})$
- **Physical Consequence**:
    - If $r3$ is positive ($+1.5\ \text{m/s}^2$) and $\text{cfg}[0x1c]$ is calibrated to $+0.5\ \text{m/s}^2$, $r3$ is capped downwards to $+0.5\ \text{m/s}^2$.
    - If $r3$ is strongly negative (heavy braking, e.g. $-3.0\ \text{m/s}^2$), $r3 < \text{cfg}[0x1c]$, so `isellt` leaves $r3$ completely untouched!
- **Conclusion**: The post-min clamping in `0xd0c58` is an **upper ceiling cap** restricting maximum forward acceleration. It does **not** limit brake pressure or maximum deceleration. True lower saturation floors occur downstream.

## 6. Coupling to Downstream Rate Limiter

Procedure `0xd0c58` does **not** emit actuator or CAN commands directly. Instead, its output (`obj+0x70`) is relayed into global buffer `G`, where it populates the **upper ceiling bound (`hi`)** of downstream rate limiter `0x7c702` / `0x79c40`.

```
0xd0c58 Return Value (r3)
  │
  ▼ [0xdb584]
obj+0x70 (Class B instance 0x400497F8)
  │
  ▼ [0xd0b6c Method, Slot +0x30]
Buffer G (0x4001AC50):
  ├── G+0x4 (lo) = max(obj+0x72, floor @ 0x40013b4a)       (Lower Floor)
  └── G+0x6 (hi) = max(obj+0x70, G+0x4)                    (Upper Ceiling Bound)
        │
        ▼ [0x7c702 Rate Limiter Ingestion]
Argument Setup:
  ├── r7 = hi = G+0x6
  ├── r8 = lo = max(Cal+0x40/42, G+0x4, Cal+0x94)
  └── r9 = dt = 41 counts (~20 ms)
        │
        ▼ [0x79c40 Core Rate Limiter]
  Slew Rate Shaper: a + clamp(b - a, dn, up)  [0x79baa]
        │
        ▼ [0x79c60..62: isellt r3, r3, r30, cr0]
  UN-RATE-LIMITED UPPER CLAMP: min(candidate, hi)
        │
        ▼ [0x7c9cc]
  Committed to cmd_obj + 0x10
```

### 6.1 Buffer Relay via Method `0xd0b6c`

Periodic method `0xd0b6c` (Class B vtable `0x15d808` slot `+0x30`, lines `192070` – `192135` of `full.dis`) populates communication buffer `G` (`0x4001AC50`, anchored at SDA slot `-0x74b0(r13)`):

```assembly
assembly
0xd0ba6  38de0072  e_lha r6, 0x72(r30)         # r6 = obj+0x72
0xd0baa  380c3b4a  e_lha r0, 0x3b4a(r12)       # r0 = calibrated floor limit @ 0x40013b4a
0xd0bba  7c06005e  iselgt r0, r6, r0, cr0      # r0 = max(obj+0x72, floor)  [TRUE BRAKE FLOOR]
0xd0bb6  393e0070  e_lha r9, 0x70(r30)         # r9 = obj+0x70 (Output of 0xd0c58)
0xd0bd8  7d09005e  iselgt r8, r9, r0, cr0      # r8 = max(obj+0x70, r0)      [hi >= lo invariant]
0xd0c0c  512d8b50  e_lwz r9, -0x74b0(r13)      # r9 = 0x4001AC50 (Buffer G)
0xd0c10  5c090004  e_sth r0, 0x4(r9)           # G+0x4 = r0 (Lower Bound lo)
0xd0c14  516d8b50  e_lwz r11, -0x74b0(r13)     # r11 = 0x4001AC50
0xd0c18  5d0b0006  e_sth r8, 0x6(r11)          # G+0x6 = r8 (Upper Bound hi)
```

> **Corrected 2026-10-04:** the `iselgt` "max" claims at 0xd0bba / 0xd0bd8 are **unproven**: the compare that sets
> cr0 is not printed [CONFIRMED static: PDF hex re-decode].

### 6.2 Rate Limiter Ingestion (`0x7c702`)

Function `0x7c702` loads buffer `G` via alias slot `-0x7bc0(r13)` (`0x4001F6F0 - 0x4aa0 = 0x4001AC50`):

```assembly
assembly
0x7c7d2  510d8440  e_lwz r8, -0x7bc0(r13)      # r8 = 0x4001AC50 (Buffer G)
0x7c7de  3b880006  e_lha r28, 0x6(r8)          # r28 = G+0x6 (Upper Ceiling hi)
0x7c7e2  3aa80004  e_lha r21, 0x4(r8)          # r21 = G+0x4 (Lower Floor lo)
```

At `0x7c81c` – `0x7c826`, candidate lower bound `r20` is clamped against calibrated floors (`Cal+0x40` = −18,432, `Cal+0x42` = −32,768, and secondary floor `*(r29 + 0x94)` = −12,288):

```assembly
assembly
0x7c81c  7c14a800  cmpw cr0, r20, r21          # Compare r20 vs G+0x4
0x7c820  7fb4a85e  iselgt r29, r20, r21, cr0   # r29 = max(r20, G+0x4)
0x7c824  0c0d      se_cmp r29, r0              # Compare r29 vs *(r29 + 0x94)
0x7c826  7fbd005e  iselgt r29, r29, r0, cr0    # r29 = max(r29, *(r29 + 0x94)) -> lo
```

Arguments are passed to core limiter `0x79c40` at `0x7c9a6` – `0x7c9ac`:

- `r7 = r28`: Upper bound ceiling `hi = G+0x6` (derived from `0xd0c58`)
- `r8 = r29`: Lower bound floor `lo`
- `r9 = 0x29 = 41`: Loop period $dt$

### 6.3 Core Limiter Dynamics (`0x79baa` / `0x79c40`)

1. **Slew Rate Step Computation (`0x79baa`)**: Maximum permitted delta steps per call are calculated via helper `0x9c200`:
   $\text{up} = \text{sat}_{16}\!\left(\frac{U \times dt}{512}\right), \quad \text{dn} = \text{sat}_{16}\!\left(\frac{D \times dt}{512}\right)$
   For Call A (`obj+0x26 == 1`), the downward deceleration ramp is fixed to `Cal+0x74 = -2560` ($-1.25\ \text{m/s}^2$ in Q11):
   $\text{dn} = \frac{-2560 \times 41}{512} = -205\ \text{counts/call} \quad (-0.1001\ \text{m/s}^2 \text{ per } 20\ \text{ms} = -5.0\ \text{m/s}^3)$
   The slew-limited candidate is evaluated:
   $r3 = \text{prev} + \text{clamp}(\text{target} - \text{prev}, \text{dn}, \text{up})$
2. **Un-Rate-Limited Clamping Against `hi` (`0x79c40`)**: Inside `0x79c40` at lines `0x79c60` – `0x79c62`:

   ```assembly
   assembly
   0x79c60  0ce3      se_cmp r3, r30              # Compare candidate r3 vs r30 (hi = G+0x6)
   0x79c62  7c63f01e  isellt r3, r3, r30, cr0     # r3 = (r3 < r30) ? r3 : r30 -> min(r3, G+0x6)
   ```

   Output $r3$ is clamped against `hi` and stored to `cmd_obj+0x10` at `0x7c9cc`.

### 6.4 The Dual Dynamic Phenomenon: Single-Frame Collapse Dynamics

The interaction between the un-rate-limited upper bound `hi` and the $-5.0\ \text{m/s}^3$ slew limiter explains a prominent empirical phenomenon observed in vehicle CAN logs:

- **Steady-State Following**: When radar demand changes gradually, the rate limiter enforces smooth transitions, capping acceleration drops to $-10$ counts/frame ($-0.10\ \text{m/s}^2$ per 20 ms). Over 99% of deceleration frames in normal driving obey this gentle slew limit.
- **Single-Frame Command Collapse**: If radar demand $b$ drops suddenly (e.g. an aggressive cut-in or lead vehicle emergency brake), the output of `0xd0c58` plunges instantaneously. This collapses `obj+0x70` and pulls down `G+0x6` (`hi`) within a single 20 ms cycle. Because instruction `0x79c62` executes an **un-rate-limited clamp against `hi`**, candidate acceleration $r3$ is immediately truncated downwards, bypassing the slew rate limiter. Real-world logs verify single-frame command drops of up to $-2.14\ \text{m/s}^2$ (e.g., $+1.01\ \text{m/s}^2 \rightarrow -1.13\ \text{m/s}^2$) in a single 20 ms frame without triggering firmware faults.

> **Corrected 2026-10-04:** "-10 counts/frame (-0.10 m/s²)" is in CAN 0.01 m/s² units; in Q11 it is **-205
> counts** [CONFIRMED static: arithmetic].

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand.

## 7. Mode 2 Gas/Brake Arbitration & Actuator Command Formation

```
cmd_obj + 0x10 (Rate Limiter Output)
  │
  ▼ [0x79624 Getter -> 0x7a424 Store]
P+0x2 (0x4001ACF2)
  │
  ▼ [0xef524 Ingest]
Mode 2 Candidate: r13 - 0x3784
  │
  ▼ [0xea40e Mode Arbiter]
Mode Arbiter 0xea40e (Mode 2 Active Tracking):
  ├── ACCEL: S+0xc = clamp(cand, -8192, +4096)  [0xeab9e Sole Writer]
  ├── BRAKE_REQ: S+0x2a b15 <= 14-State FSM      [0xeabfa / 0xeac0c]
  └── GAS_CMD: S+0x8 <= Sentinel -30000          [0xea4ac]
```

### 7.1 Path from Rate Limiter to Mode Arbiter

1. Limiter output `cmd_obj+0x10` is loaded by getter `0x79624`.
2. Stored to $P + 0x2$ (`0x4001ACF2`) via slot `-0x7b9c(r13)` at `0x7a424`.
3. Ingest routine `0xef4f8` loads $P + 0x2$ via alias slot `-0x7248(r13)` and transfers it into the Mode 2 candidate field:

   ```assembly
   assembly
   0xef508  59280002  e_lhz r9, 0x2(r8)           # r9 = P+0x2
   0xef524  5d3efff4  e_sth r9, -0xc(r30)         # *(r13 - 0x3784) = r9 (Mode 2 Candidate)
   ```

### 7.2 Mode Arbiter `0xea40e` Execution

Mode Arbiter `0xea40e` governs longitudinal control modes (Mode 0: Disabled, Mode 1: Override, Mode 2: Stock ACC Active, Mode 3: Disengaging, Mode 4: Standstill Hold):

- Evaluates mode byte at `r13 - 0x3788`.
- In Mode 2 (active tracking), copies candidate `r13 - 0x3784` into working register `r31` at `0xeaa08` – `0xeaa10`.
- Clamps candidate against calibrated dynamic floor `r27 + 0x458` ($-8192 = -4.0\ \text{m/s}^2$ in Q11).
- Commits final acceleration to Structure `S` (`0x400396FC`) via slot `-0x7210(r13)`:

  ```assembly
  assembly
  0xeab9a  50cd8df0  e_lwz r6, -0x7210(r13)      # r6 = 0x400396FC (Struct S)
  0xeab9e  b6f6      se_sth r31, 0xc(r6)         # S+0xc = r31 (ACCELERATION COMMAND)
  ```

- **Firmware Invariant**: Automated binary scan (`scan_SplusOxc_writers.py`) confirms that `0xeab9e` is the **sole writer of $S + 0xc$** across the entire firmware image.

### 7.3 Decoupling of `ACCEL_COMMAND` and `BRAKE_REQUEST`

A foundational architectural discovery in `mode2_scratch.md` is that CAN signal `BRAKE_REQUEST` (bit 34) is **decoupled from the arithmetic sign of `ACCEL_COMMAND`**:

- In naive models, it was assumed that `BRAKE_REQUEST = 1` if and only if $\text{ACCEL\_COMMAND} < 0$.
- Telemetry analysis of 167,295 stock ACC frames revealed 4,560 frames where $\text{ACCEL\_COMMAND} > 0$ while $\text{BRAKE\_REQUEST} == 1$.
- In firmware assembly, `BRAKE_REQUEST` maps to bit 15 of word $S + 0x2a$, set at `0xeabfa` (`or2i r12, 0x8000`) and cleared at `0xeac0c` (`andi r9, 0xffff7fff`).

#### Determinants of `BRAKE_REQUEST` Bit 15

Bit 15 is asserted if **ANY** of the following four conditions is satisfied:

1. **Debounced Interface Byte**: Byte at `r13 - 0x378c == 1` (ingested at `0xf018c` from module input `r13 - 0x6a54`).
2. **FSM Braking Mode (Bit 11)**: Bit 11 of status word `*(0x4001B018)` is set (asserted at `0xc3306` when 14-state supervisory FSM `r13 - 0x3ebc \in \{6, 7, 12, 13\}$`).
3. **FSM Standstill / Transition Mode (Bit 6)**: Bit 6 of status word `*(0x4001B018)` is set (asserted at `0xc34c6` when FSM `r13 - 0x3ebc \in \{3, 4\}$`).
4. **Latched Braking Flag**: Bit 7 of flag byte `*r28` (`r13 - 0x374c`) is set (`*r28 & 0x80 != 0`).

*Critical Assembly Ground Truth*: None of these four conditions inspects register `r31` or field $S + 0xc$ (`ACCEL_COMMAND`). Consequently, the radar ECU holds `BRAKE_REQUEST` asserted during brake-to-throttle handoffs, hydraulic pre-fill priming, and standstill hold releases even while commanding positive acceleration up to $+1.30\ \text{m/s}^2$.

#### `GAS_COMMAND` Formulation

Simultaneously, `GAS_COMMAND` ($S + 0x8$, 16 bits signed, bit 8 of `0x1DF`) is populated at `0xea4ac`:

- During active brake intervention or standstill hold, $S + 0x8$ holds sentinel value **−30000** (`0x8ad0` in two's complement).
- This sentinel signals the powertrain ECM to inhibit throttle intervention and decouple cruise drive torque while the VSA brake modulator manages vehicle deceleration.

## 8. CAN 0x1DF (`ACC_CONTROL`) Packing & Bus Serialization

CAN frame `0x1DF` (`ACC_CONTROL`) is broadcast over Bus 0 (ACC-CAN) and Bus 1 (Powertrain CAN) at 50 Hz.

```
Struct S Base: 0x400396FC
  ├── S+0xc  (s16 Q11) ──> Packer 0xdf444 ──> Desc 0x15e938 ──> ACCEL_COMMAND (31|11)
  ├── S+0x2a (b15)     ──> Packer 0xdf364 ──> Signal ID 0x11 ──> BRAKE_REQUEST (bit 34)
  └── S+0x8  (s16)     ──> Packer 0xdf3a0 ──> Signal ID 0x14 ──> GAS_COMMAND (bit 8)
```

> **Corrected 2026-10-04:** see correction (g) — `GAS_COMMAND` DBC start bit is 7 with LSB 8; `ACCEL_COMMAND` is `31|11@0-`, LSB 37.

### 8.1 Packer Routine `0xdf444` Mechanics

Packer routine `0xdf444` reads $S + 0xc$ via SDA slot `-0x738c(r13)`:

```assembly
assembly
0xdf440  50ed8c74  e_lwz r7, -0x738c(r13)      # r7 = 0x400396FC (Struct S)
0xdf444  3807000c  e_lha r0, 0xc(r7)           # r0 = s16 S+0xc (Q11 counts)
0xdf44c  108002d1  efscfsi r4, r0              # r4 = (float)r0 (SPE float conversion)
0xdf450  1c60e938  e_add16i r3, r0, -0x16c8    # r3 = 0x15e938 (Calibration Descriptor)
0xdf454  79fdbdb9  e_bl 0x11f608               # Call CAN linear scaling routine
```

> **Corrected 2026-10-04:** `0xdf450 1c60e938` has rA = 0 (`e_add16i r3,r0,-0x16c8`), so it cannot form
> r3 = 0x15e938 (that needs rA = r3 after an `e_lis`); the listing skips 4 bytes 0xdf444 → 0xdf44c; and
> `0xdf454 79fdbdb9` `e_bl` targets **0xbb20c**, not 0x11f608. The §8.1 listing is **unreliable as printed**
> [CONFIRMED static: PDF hex re-decode].

### 8.2 Calibration Descriptor `0x15e938` Scaling

Calibration descriptor `0x15e938` defines the scaling parameters:

$$
\text{Descriptor at } 0x15e938 = \begin{cases}
\text{max} = +10.23\ \text{m/s}^2 \\
\text{min} = -10.24\ \text{m/s}^2 \\
\text{res} = 0.01\ \text{m/s}^2 \\
\text{off} = 0.0 \\
\text{div} = 2048.0 \\
\text{mul} = 1.0
\end{cases}
$$

Linear scaling function `0x11f608` computes the CAN wire integer:

$$
\text{raw} = \text{round}\!\left(\frac{\text{counts}_{Q11}}{2048.0} \times \frac{1.0}{0.01}\right) = \text{round}\!\left(\frac{\text{counts}_{Q11}}{20.48}\right)
\qquad
\text{raw} = \text{clamp}_{[-1024,\,+1023]}(\text{raw})
$$

The resulting signed 11-bit integer is packed into bits 31–21 of CAN message `0x1DF`.

> **Corrected 2026-10-04:** see correction (g) — `ACCEL_COMMAND` occupies bits 31..24 then 39..37 (LSB 37), not "bits 31-21".

### 8.3 Wire Format & Bit Layout of CAN `0x1DF` (`ACC_CONTROL`)

Broadcast cadence: **50.0 Hz (20.0 ms period)**. Payload length: **8 bytes**.

| Signal Name | Start Bit | Bit Length | Endianness | Type | Scale | Offset | Physical Range | Signal ID | Description |
|---|---|---|---|---|---|---|---|---|---|
| `ACCEL_COMMAND` | 31 | 11 | Motorola | Signed | 0.01 m/s² | 0.0 | [−10.24, +10.23] m/s² | — | Primary longitudinal acceleration command |
| `BRAKE_REQUEST` | 34 | 1 | Motorola | Boolean | 1 | 0 | {0, 1} | `0x11` | Active braking intervention request |
| `GAS_COMMAND` | 8 | 16 | Motorola | Signed | 1 | 0 | [−32768, +32767] | `0x14` | Powertrain drive throttle command (−30000 = inhibit) |
| `STANDSTILL` | 35 | 1 | Motorola | Boolean | 1 | 0 | {0, 1} | `0x17` | Vehicle standstill hold latch |
| `AEB_PREPARE` | 43 | 1 | Motorola | Boolean | 1 | 0 | {0, 1} | `0x1d` | Hydraulic brake pre-fill priming |
| `BRAKE_LIGHTS` | 62 | 1 | Motorola | Boolean | 1 | 0 | {0, 1} | `0x1e` | Brake lamp illumination request |
| `COUNTER` | 59 | 4 | Motorola | Unsigned | 1 | 0 | [0, 15] | — | Cyclic message counter |
| `CHECKSUM` | 55 | 4 | Motorola | Unsigned | 1 | 0 | [0, 15] | — | Honda CAN checksum nibble |

> **Corrected 2026-10-04:** `COUNTER` is 61|2 and `CHECKSUM` 59|4 (was 59/4 and 55/4); `ACCEL_COMMAND` is
> `31|11@0-` (0.01) and occupies bits 31..24 then 39..37 (LSB 37), not "bits 31-21"; `GAS_COMMAND` DBC start bit is
> 7 with LSB 8 ("bit 8" is the LSB). The original table omitted `CONTROL_ON`, `SET_TO_0`, `AEB_STATUS`,
> `AEB_BRAKING`, `STANDSTILL_RELEASE` [CONFIRMED static: opendbc DBC]. Firmware TX descriptor ids: 0x0a
> ACCEL_COMMAND 11/LSB 37, 0x14 GAS_COMMAND 16/8, 0x11 BRAKE_REQUEST 1/34, 0x1d AEB_PREPARE 1/43, 0x10/0x17/0x0f/0x1e
> = AEB_STATUS 33, STANDSTILL 35, STANDSTILL_RELEASE 36, BRAKE_LIGHTS 62 [FIRMWARE TRACE by xcheck 2026-10-03, not
> re-run here].

### 8.4 Closed-Form End-to-End Mathematical Transfer Function

The full transfer function from physical inputs to the transmitted CAN `ACCEL_COMMAND` wire signal is given by:

$$
\begin{aligned}
\text{Ego Accel } a &= \text{sat}_{16}\!\left(Y + \text{sat}_{16}\!\left(\frac{Y \cdot K}{2^{18}}\right)\right), \quad Y = \text{IIR}_2\!\left(\text{sat}_{16}\!\left(\frac{\Delta v_{\text{ref}} \ll 14}{41}\right)\right) \\
\text{Radar Demand } b &= \text{FIR}_5\big(\text{neg\_sat}_{16}(\text{sat}_{16}(\text{round}(98.0 \cdot \text{raw}_{\text{COM}} - 50176.0)))\big) \\
r_3 &= \min(a, b) \\
\text{Ceiling } hi &= \begin{cases}
\min(r_3, \text{cfg}[0x1c]) & \text{if cfg}[0] \in \{1, 2\} \\
\min(r_3, \text{cfg}[0x18]) & \text{if cfg}[3] \in \{1, 2\} \\
r_3 & \text{otherwise}
\end{cases} \\
\text{Command } u[k] &= \max\big(lo,\ \min\big(u[k-1] + \text{clamp}(\text{target} - u[k-1],\ dn,\ up),\ hi\big)\big) \\
\text{Arbitrated } S[0xc] &= \text{clamp}(u[k],\ -8192,\ +4096) \\
\text{CAN\_RAW} &= \text{clamp}_{[-1024,\,+1023]}\!\left(\text{round}\!\left(\frac{S[0xc]}{20.48}\right)\right)
\end{aligned}
$$

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand.

> **Corrected 2026-10-04:** see correction (h) — the IIR_2 stage constants imply ~8.0 s / ~1.6 s time constants; implausible for a brake path, needs re-trace.

## 9. Verification Runbook & Evidence Matrix

### 9.1 Hardware Registers, Memory Map & SDA Slot Cross-Reference Table

The table below catalogs every critical memory address, Small Data Area offset, register binding, and firmware disassembly PC across the entire pipeline:

| Logical Subsystem | Physical Address | SDA Offset / Pointer | Register | Size / Type | Disassembly PC | Semantic Description |
|---|---|---|---|---|---|---|
| **Ego Speed $v_i$** | `0x400492C4 + 0x4e + 2i` | Struct S | — | `int16_t[4]` | `0xbca4a` | Conditioned wheel speeds (1/256 m/s, Q8) |
| **Gear Direction** | `0x4001F6F0 - 0x3eee` | `-0x3eee(r13)` | `r13` | `int8_t` | `0xbcdf8` | Driving direction flag (`+1` forward, `-1` reverse) |
| **Speed Reference** | `0x4001A458 - 0x16` | `-0x16(r29)` | `r29` | `int16_t` | `0x72d4e` | 5-tap moving average speed reference (1/256 m/s) |
| **Filtered Accel $Y$** | `0x4001A458 - 0xa` | `-0xa(r29)` | `r29` | `int16_t` | `0x72ea4`, `0x730e8` | Dual IIR filtered ego acceleration (1/2048 m/s², Q11) |
| **Calibration Trim $K$** | `0x4001AA82` | `+0x2(*(r13 - 0x7c88))` | `r11` | `int16_t` | `0x730ec` | Multiplicative calibration trim factor |
| **Struct A (Writer)** | `0x4003B144` | `-0x7c70(r13)` | `r12` | Pointer | `0x76836`, `0x73100` | Struct A base pointer (`0x40040000 - 0x4ebc`) |
| **Struct A (Reader)** | `0x4003B144` | `-0x7588(r13)` | `r10` | Pointer | `0xc4eca`, `0xd0c58` | Struct A consumer pointer |
| **Input $a$ (Field)** | `0x4003B15C` | `+0x18(*(r13 - 0x7588))` | `r10` | `int16_t` | `0x73104`, `0xd0c64` | **Ego Longitudinal Acceleration (Q11)** |
| **COM Float Table** | `0x16661c` | ROM (File `0x13661c`) | `r3` | `float[4]` | `0x143678` | [0.0478515625, −24.5, 2048.0, 1.0] |
| **COM Demand Rec** | `0x40036A9C + 0x196` | `+0x196(*(r13 - 0x766c))` | `r6` | `int16_t` | `0x1436a4`, `0xbc5d2` | Scaled cruise demand from COM 0x276 (Q11) |
| **Negated Demand** | `0x4001AA12` | `+0x12(*(r13 - 0x7660))` | `r10` | `int16_t` | `0xbc5fc`, `0x70986` | Negated cruise demand (−COM_Demand) |
| **Demand Status** | `0x4001AA33` | `+0x33(*(r13 - 0x7660))` | `r7` | `uint8_t` | `0xbc618`, `0x7096e` | Source demand status byte (Bit 0 tested) |
| **FIR Delay Line** | `0x4001A340` | `-0x53b0(r13)` | `r11` | `int16_t[4]` | `0x70910`, `0x70950` | 5-sample MA FIR delay line array |
| **Struct B (Writer)** | `0x4001A9F0` | `-0x7c74(r13)` | `r8` | Pointer | `0x767a8`, `0x70998` | Struct B base pointer (`0x4001F6F0 - 0x4d00`) |
| **Struct B (Reader)** | `0x4001A9F0` | `-0x7598(r13)` | `r9` | Pointer | `0xc4ed6`, `0xd0c5c` | Struct B consumer pointer |
| **Input $b$ (Field)** | `0x4001A9F0` | `+0x0(*(r13 - 0x7598))` | `r0` | `int16_t` | `0x7099c`, `0xd0c68` | **Filtered Negated Radar Demand (Q11)** |
| **Config Struct M** | `0x4001AD08` | `-0x7524(r13)` | `r12` | Pointer | `0xc4f36`, `0xd0c60` | Configuration structure base |
| **Ceiling Limit 1** | `0x4001AD24` | `+0x1c(*(r13 - 0x7524))` | `r10` | `int16_t` | `0xd0c8a` | Calibrated acceleration ceiling cfg[0x1c] |
| **Ceiling Limit 2** | `0x4001AD20` | `+0x18(*(r13 - 0x7524))` | `r10` | `int16_t` | `0xd0ca4` | Calibrated acceleration ceiling cfg[0x18] |
| **Brake Law Output** | `0x400497F8 + 0x70` | `+0x70(r31)` | `r3` | `int16_t` | `0xdb584`, `0xd0bb6` | Class B command object field `obj+0x70` |
| **Buffer G Base** | `0x4001AC50` | `-0x74b0`, `-0x7bc0` | `r9` / `r8` | Pointer | `0xc4de4`, `0x7c530` | Rate limiter buffer base (`0x4001F6F0 - 0x4aa0`) |
| **Limiter Lower Bound** | `0x4001AC54` | `G + 0x4` | `r0` / `r21` | `int16_t` | `0xd0c10`, `0x7c7e2` | Rate limiter lower floor `lo` |
| **Limiter Upper Bound** | `0x4001AC56` | `G + 0x6` | `r8` / `r28` | `int16_t` | `0xd0c18`, `0x7c7de` | Rate limiter upper ceiling `hi = max(obj+0x70, G+0x4)` |
| **Limiter Output** | `cmd_obj + 0x10` | `+0x10(r30)` | `r3` | `int16_t` | `0x7c9cc`, `0x79624` | Rate-limited acceleration command |
| **Candidate Field P** | `0x4001ACF2` | `P + 0x2` (`-0x7b9c`, `-0x7248`) | `r8` | `int16_t` | `0x7a424`, `0xef508` | Relay slot $P$ = 0x4001F6F0 − 0x4a00 |
| **Mode 2 Candidate** | `r13 - 0x3784` | `-0x3784(r13)` | `r9` | `int16_t` | `0xef524`, `0xeaa10` | Mode 2 active acceleration candidate |
| **Struct S Base** | `0x400396FC` | `-0x7210`, `-0x738c` | `r6` / `r7` | Pointer | `0xe4f7c`, `0xdffde` | Persistent actuator state structure base |
| **Final Command** | `0x40039708` | `S + 0xc` | `r31` / `r0` | `int16_t` | `0xeab9e`, `0xdf444` | **Sole Writer Site** for ACCEL_COMMAND |
| **Brake Request Flag** | `0x40039726` | `S + 0x2a` (bit 15) | `r12` | Bitfield | `0xeabfa`, `0xdf364` | `BRAKE_REQUEST` CAN control flag |
| **Gas Inhibit Command** | `0x40039704` | `S + 0x8` | `r0` | `int16_t` | `0xea4ac`, `0xdf3a0` | `GAS_COMMAND` (Sentinel −30000) |
| **CAN Descriptor** | `0x15e938` | Flash Descriptor | `r3` | Struct | `0xdf450` | Linear scale descriptor (`div = 2048.0, res = 0.01`) |

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand. (Rows "COM Demand Rec", "Negated Demand", "Demand Status", "Input b (Field)".)

> **Corrected 2026-10-04:** see correction (d) — `0x72d4e` decodes as `e_sth r3,-0x18(r13)`; the "Speed Reference" store at `-0x16(r29)` is not supported by its own hex.

> **Corrected 2026-10-04:** see correction (e) — `0xdf450` cannot form r3 = 0x15e938 ("CAN Descriptor" row).

### 9.2 Runnable Python Reproduction Scripts

The following scripts allow direct, deterministic reproduction and verification of all findings against the repository binaries.

#### Test 1: Verify Assembly Trace of Ego Path $a$ and Function Bounds

```bash
bash
python3 -c "
with open('/Users/peternguyen/firmware-analysis-kit/recheck_2026-10-01/fw_acc_formula/dis/full.dis') as
f:
    lines = f.readlines()

def check_line(pc, expected):
    found = [l.strip() for l in lines if l.startswith(pc + ' ')]
    assert found, f'PC {pc} not found'
    assert expected in found[0], f'Mismatch at {pc}: found {found[0]}, expected {expected}'
    print(f'PASS: {found[0]}')

check_line('0x725d2', 'e_stwu r1,-0x70(r1)')
check_line('0x725e0', 'e_add16i r29,r13,-0x5298')
check_line('0x730e8', 'e_lha r3,-0xa(r29)')
check_line('0x730ec', 'e_lha r4,0x2(r11)')
check_line('0x730f2', 'e_bl 0x9c200')
check_line('0x730fc', 'e_bl 0x9c1a2')
check_line('0x73104', 'e_sth r3,0x18(r12)')
check_line('0x73128', 'e_lha r3,-0x1a(r29)')
check_line('0x7332c', 'se_blr')
print('Input a disassembly path verified completely.')
"
```

#### Test 2: Verify Arithmetic Helpers (Division by 5 & Saturating Negation)

```bash
bash
python3 -c "
import ctypes

def div5_asm(n):
    r8 = 0x66666667
    prod = ctypes.c_int64(r8 * n).value
    mulhw = prod >> 32
    sign = -1 if n < 0 else 0
    return (mulhw >> 1) - sign

for x in range(-163840, 163840, 17):
    expected = int(x / 5)
    assert div5_asm(x) == expected, f'div5 mismatch for {x}: {div5_asm(x)} vs {expected}'
print('PASS: 5-sample division by 5 verified across 327,680 test values.')

def sat_neg16(x):
    return 0x7fff if x == -0x8000 else -x
assert sat_neg16(-32768) == 32767
assert sat_neg16(100) == -100
assert sat_neg16(-500) == 500
print('PASS: Saturating negation helper 0x9c308 verified.')
"
```

#### Test 3: Verify Calibration Table `0x16661c` Floats & Q11 Scale

```bash
bash
python3 -c "
import struct
bin_path = '/Users/peternguyen/firmware-analysis-kit/radar-re/36802TBA.dec.bin'
with open(bin_path, 'rb') as f:
    data = f.read()

offset = 0x16661c - 0x30000
floats = struct.unpack('>4f', data[offset : offset + 16])
print('Calibration parameters at 0x16661c:', floats)
assert floats == (0.0478515625, -24.5, 2048.0, 1.0), 'Float calibration table mismatch'
t0, t1, t2, t3 = floats
assert t2 == 2048.0, 'Scale factor is not 2048.0 counts per m/s^2'
print('PASS: COM 0x276 calibrated units confirmed as 1/2048 m/s^2 (Q11 format).')
"
```

#### Test 4: Verify Buffer Relay & Rate Limiter Bound Aliasing

```bash
bash
python3 /Users/peternguyen/firmware-analysis-kit/recheck_2026-10-01/fw_acc_formula/
verify_bounds_alias_2026-10-02.py
```

*Expected Output*:

```text
text
OK   0xd0c18 e_sth r8,0x6(r11)
OK   0x7c7de e_lha r28,0x6(r8)
OK   0x7c7e2 e_lha r21,0x4(r8)
OK   0x7c7d2 e_lwz r8,-0x7bc0(r13)
OK   vtable[0x7c] @0x15d884 = 0xd0c58
FAILS 0
```

#### Test 5: Verify Full Downstream Chain to CAN Packer

```bash
bash
python3 /Users/peternguyen/firmware-analysis-kit/recheck_2026-10-01/fw_acc_formula/mode2_Sa_anchor.py /
Users/peternguyen/firmware-analysis-kit/radar-re/36802TBA.dec.bin
```

*Expected Output*:

```text
text
checks 47, FAILS 0
RESULT: solver output A reaches ACCEL_COMMAND with no rescaling; packer computes raw = A/2048/0.01.
        => Sa = 1/2048 m/s^2 (given ACCEL_COMMAND = 0.01 m/s^2, opendbc). With Sv = 1/256 (anchor #2) and
        Sv^2 = 4 Sd Sa:  Sd = 2^-16 / (4 * 2^-11) = 2^-7 = 1/128 m.
OK  Sd = 1/128 m
```

### 9.3 Comprehensive Audit Verdict Matrix

| Analytical Dimension | Claim in `acc_brake_notes.md` | Authoritative Verified Reality | Verdict |
|---|---|---|---|
| **Ego Accel ($a$) Origin** | Internal ego-tracking parameter | Derived strictly from 4 wheel speed sensors via midrange average, numerical differentiator `0x9b320` ($dt = 41$), and dual cascaded IIR filters. | **FACTUAL & PROVEN** |
| **Input $a$ Writer Boundary** | Function ends at `0x73128` | Function begins at `0x725d2` and terminates at `0x7332c` (3,418 bytes); `0x73128` is an internal load. | **INCORRECT** |
| **Input $a$ Writer Identity** | Labeled as "`B` writer `0x725d2`" | Routine `0x725d2` writes input $a$ (`*(0x4003B144 + 0x18)`). Input $b$ is written by `0x7095a`. | **INCORRECT** |
| **Input $a$ Calibration** | Trim factor omitted | Formula: $a = \text{sat}_{16}(Y + \text{sat}_{16}((Y \times K) \gg 18))$ where $K = *(0x4001AA82)$. | **FACTUAL (Formula) / OMISSION ($K$)** |
| **Radar Demand ($b$) Origin** | COM signal `0x276` | Sourced from COM `0x276`, companion `0x274` validated, table `0x16661c` float scaled, negated at `0xbc5f2`, 5-tap filtered at `0x7090a`. | **FACTUAL & PROVEN** |
| **Input $b$ Units** | "Likely 1/256 m/s²" | Multiplier $t_2 = 2048.0$ in table `0x16661c`; format is signed 16-bit **Q11** (1/2048 m/s²). | **INCORRECT (8× Error)** |
| **Input $b$ Filter Gating** | "Gated by status bit in `0x4001A9F4`" | Gate tests source status byte `*(0x4001AA00 + 0x33)` bit 0. `0x4001A9F4` is destination flags (`\|= 0xc0`). | **PARTIALLY FLAWED** |
| **`0xd0c58` Law Operation** | Computes `min(a, b)` | Signed algebraic minimum $\min(a,b)$ executed via PowerPC `cmpw` + `isellt`. | **FACTUAL** |
| **Physical Law Meaning** | "Safety min-select against target deceleration" | Negated demand maps into signed acceleration; $\min$ selects the **most negative value** (strongest braking effort). | **FLAWED PHRASING** |
| **Post-Min Clamping Role** | "Saturating against active brake limits" | Upper ceiling cap: $r3 \leftarrow \min(r3, \text{cfg})$. Caps forward acceleration; does not enforce a deceleration floor. | **FLAWED INTERPRETATION** |
| **Actuator Command Path** | Direct brake command generator | Relayed by `0xd0b6c` into rate limiter upper ceiling bound $G + 0x6$ (`hi`); arbitrated at `0xea40e`; packed by `0xdf444`. | **ARCHITECTURALLY FLAWED** |
| **Brake Request Condition** | Tied to deceleration demand | Controlled by 14-state supervisory FSM (`r13 - 0x3ebc`); completely decoupled from `ACCEL_COMMAND` sign. | **DISCOVERY (mode2_scratch)** |

> **Corrected 2026-10-04:** see correction (a) — input b is KINEMATICS 0x094 LONG_ACCEL (VSA measured accel), not a demand. (Rows "Radar Demand (b) Origin", "Physical Law Meaning".)

> **Corrected 2026-10-04:** see correction (b) — "companion `0x274` validated" is unproven (1-bit field at LSB 52 of 0x094).

> **Corrected 2026-10-04:** see correction (h) — the "dual cascaded IIR filters" give ~8.0 s / ~1.6 s time constants; implausible for a brake path, needs re-trace.

<!-- NEW SECTIONS BELOW -->

## 10. Check against the current openpilot radard, planner and Bosch command path

*Added 2026-10-04. Static reading of this repository at HEAD `6fd6eed` (`git show HEAD:…`), plus the replay
evidence already recorded in `STATUS.md`. Nothing in this section has been road-validated.*

> **Warning — in-flight staged edits.** At the time of writing, another session has 27 files staged but
> not committed in this checkout. They undo several HEAD behaviours: newborn range publishing defaults off,
> `ADJACENT_RAIL_CONFIRM` is deleted, the `BoschAU11Scale72` toggle returns (1/64 when off), the D-076
> range-offset fallback is removed, and the planner's `BRAKE_RELEASE_DWELL` / `COAST_CEILING_SLEW` and
> longcontrol's Resume Brake Ramp are removed. Everything below describes **HEAD**, not the staged tree.
> Turning newborn publishing off would delete radar points, which CLAUDE.md rule 4 ranks as the more
> dangerous failure. Diff those files before anyone commits them.

### 10.1 What the firmware chain consumes, and what openpilot consumes

| Quantity | Radar firmware (this report, corrected) | openpilot at HEAD |
|---|---|---|
| Ego accel from wheel speeds | `a`: 0x1D0 WHEEL_SPEEDS → 5-tap mean → differentiator → IIR (§2.2) | `aEgo` = derivative state of `update_speed_kf(vEgoRaw)`, wheel speeds 0x1D0 blended with XMISSION_SPEED (`carstate.py:133-137`, KF Q=[[0,0],[0,100]], R=0.3) |
| Ego accel from the VSA accelerometer | `b`: 0x094 KINEMATICS LONG_ACCEL, 10 bits at LSB 32, ×49/1024 −24.5, negated (§2.3, correction a/b) | **Not read anywhere.** Only `YAW_RATE` from 0x094 is used (`carstate.py:203-204`) |
| Ego-accel bound used by the ACC law | `min(a, b)` at 0xd0c58, clamped by cfg[0x1c]/[0x18] | None. The planner seeds `a_desired` with `clip(aEgo)` (`longitudinal_planner.py:2775`) |
| Brake-onset slew | ≈ −5 m/s³ limiter in the ACC law (§6) | **None.** Only a release-side limit, `BRAKE_RELEASE_JERK` 2.5 m/s³ (`longitudinal_planner.py:334, 389-393`) |
| Command floor | −4.0 m/s² stock (§9) | `ACCEL_MIN` −3.5 (`interfaces.py:39-40`); Bosch clip −3.5..2.0 every 2nd frame (`carcontroller.py:1088`) |
| Brake request | `BRAKE_REQUEST` bit with the accel command, hydraulics in the VSA (§8.3) | Braking hysteresis on < −0.12, release > −0.02 (`carcontroller.py:57-58, 228-236`); `hondacan.create_acc_commands` (lines 80-110) |

### 10.2 radard (Bosch-A path)

- The per-track KF steps at `BOSCH_A_FREQ_HZ` 14.35 (`radar_interface.py:56` → `radard.py:554, 1567`). It is a
  2-state constant-accel filter on `vLead = vRel + v_ego_hist[0]` (`radard.py:1686`).
- Honda sets `radarDelay = 0.1` (`honda/interface.py:461`). radard sizes `v_ego_hist` as
  `round(delay / DT_MDL) + 1` = 3 entries (`radard.py:1579`) and appends once per radard update when a new
  carState has arrived (`radard.py:1656-1659`). radard runs on the modelV2 poll (20 Hz, `main()`), and carState
  is 100 Hz, so the append rate is 20 Hz and `v_ego_hist[0]` is 2 × 50 ms = 0.1 s old, as configured
  (static reading; corrected in revision 3 — revision 2 said ≈ 0.14 s, wrongly assuming the append ran at the
  14.35 Hz radar rate). The 0.1 s itself was never measured for the Bosch-A radar's sweep latency. Any mismatch between that delay and the true one leaks ego acceleration into `vLead`
  and from there into `aLeadK`.
- `aLeadK = kf.x[ACCEL]` (`radard.py:882`). radard never reads `aEgo`, so `aLeadK` is effectively
  d/dt(vRel + vEgo) and inherits wheel-speed derivative noise.
- `aLeadTau` is `FirstOrderFilter(_LEAD_ACCEL_TAU=0.6, 0.45, DT_MDL)` (`radard.py:22, 728, 883-889`) but is
  stepped only on 14.35 Hz measurement updates. Each step multiplies by 0.45/0.5 = 0.9, so the wall-clock time
  constant is −1/(14.35·ln 0.9) ≈ 0.66 s instead of the ≈ 0.47 s it would have at 20 Hz, and its ×1.1 recovery
  runs 30 % slower in wall-clock time than written (static arithmetic).
- Lead selection: vision prob > 0.35 then `match_vision_to_track` (`radard.py:1345, 1428`), vision
  fallback with `aLeadTau` 0.3 (`1402-1413`), Bosch-A low-speed override (`1455-1470`). The gates are
  publish-time bounds; the D-053 range-derived vRel assist explicitly never feeds `aLeadK` (`radard.py:76`).

### 10.3 Planner, longcontrol and the Bosch command

- On Honda Bosch, longcontrol has `kpV = kiV = 0` (`honda/interface.py:104-112`, `interfaces.py:383-385`),
  so the sent `ACCEL_COMMAND` is a pure feedforward of `actuators.accel` (`carcontroller.py:920`). This
  matches the cross-check §5 and STATUS item 71 (replay: median difference 0.000, p1/p99 ±0.03).
- STATUS item 71 (replay, routes 258/237/241/24f/251/254): in the −3.0…−3.6 command bin the car
  delivers −0.25…−0.65 m/s² more than asked. Item 72 (replay, 79 onsets): over-brake is ≈ 27 % of the
  requested depth and **does not grow with onset rate** (correlation +0.46 toward *less* over-brake at
  faster onsets). Both were measured against openpilot's wheel-KF `aEgo(t+0.35)`, never against
  LONG_ACCEL.
- The firmware result in this report adds one thing those items could not see: the stock ACC law
  bounds its own command by the *minimum* of the wheel-derived and accelerometer accelerations. When
  openpilot commands longitudinal, that bound is not applied by anyone.

### 10.4 Is the stock ACC law active under openpilot longitudinal?

Not established. openpilot sends 0x1DF itself, so the radar's own TX of 0x1DF is replaced on the bus; the
firmware's −5 m/s³ limiter and `min(a,b)` bound act only on the radar's own command. Whether the radar
keeps computing the law internally (and whether anything in the VSA uses it) cannot be decided from
the firmware listings or from openpilot logs. **Static inference only:** the limiter does not shape
openpilot's command today.

## 11. Where the parser and radard can improve, based on these findings

*Proposals only. None has been run on replay or on the road. Each should land behind a toggle, default
off, and log in shadow first.*

1. **Log the VSA accel and a firmware-replica ego accel (shadow only).** Decode 0x094 LONG_ACCEL as
   `aEgoVsa` in carstate (10-bit offset-binary at LSB 32, or the DBC's 9-bit signed field; they agree
   for |raw| < 256 and differ in scale by 2.4 %). Also compute `aEgoFw` = the firmware's chain (5-tap
   mean, 20 ms differentiator, IIR, `min(a,b)`). First check that 0x094 is on the bus on the owner's
   car, and whether 0x1EA VEHICLE_DYNAMICS LONG_ACCEL is a better source. Then **re-bin STATUS item 71's
   over-delivery against `aEgoVsa`**: if the accelerometer agrees with the command where wheel-KF `aEgo`
   does not, part of the "over-delivery" is measurement, not plant.
2. **Time-align the ego reference used to build `vLead`.** Measure the Bosch-A sweep latency (e.g. by
   regressing `vRel` against ego speed during hard ego braking behind a steady lead), then size
   `radarDelay` to it. The history timebase itself is already correct (20 Hz appends, `DT_MDL` sizing; §10.2). U11 already lags closing onset by 0.88-1.28 s
   (`radard.py:737-740`, D-043/D-044), and the D-053 routes show `aLeadK` dips of −3.8/−7.2/−6.0
   (`radard.py:68-70`). Compare in shadow on those routes. This changes only the estimate, never
   whether a point is published.
3. **Fix the `aLeadTau` timebase.** Construct the filter with the Bosch-A step (1/14.35 s) or scale its
   update. Then decide `_LEAD_ACCEL_TAU` (0.6 here vs upstream 1.5) on replay evidence — compare the
   predicted `v_lead` at 1-3 s with what the lead actually did.
4. **Regress the U11 − range-rate residual on ego accel.** Fit `(U11 − d(range)/dt)` against `aEgo`
   and `aEgoVsa`. If ego acceleration or ego lag explains the open moving-lead 55-70 band of D-074,
   it is a timing effect, not a scale effect. **Do not retune the 1/72 scale on this** (CLAUDE.md rule
   5: two constants were re-tuned on offline statistics and regressed on the road).
5. **Log a stock-equivalent slewed command.** Record what openpilot's command would be after a
   −5 m/s³ onset slew, without sending it. STATUS item 72 found no support for an onset jerk limit,
   and item 71 option 3 forbids scaling saturated commands; logging lets the question be reopened on
   evidence.
6. **Floor.** Keep `ACCEL_MIN` −3.5 against stock −4.0. No change proposed.

Never use any of the above to delete or coast a radar point (D-041, D-042, rule 4).

## 12. Upstream openpilot comparison and braking proposals

*Sources: upstream openpilot `master` `ec95db3f1fa19f76940497fedfdb62e09ea19912` and opendbc `master`
`35f7e0813462607ef1d703e52313e7571e31405d` (both 2026-10-02), read statically; paths now live under
`openpilot/selfdrive/controls/` in upstream's monorepo layout. Every item in §12.3 is a proposal with no
replay or road evidence.*

### 12.1 Upstream today

- **MPC is lead-only** (`MPC_SOURCES = (lead0, lead1)`, `long_mpc.py:26`). Cruise is a separate
  jerk-limited law, `get_cruise_accel()`: target `clip(v_cruise − v_ego, A_CRUISE_MIN −1.2, max)`,
  slewed by `J_CRUISE_VALS` [1.6, 1.2, 0.8, 0.6] m/s³ at [0, 10, 25, 40] m/s, plus a lateral-accel budget
  and a pitch-aware coast cap `−5.65·sin(pitch) − 0.3` when the model's gas probability ≤ 0.4.
- **Output = min over candidates** (MPC, cruise, and in experimental mode the model's
  `desiredAcceleration`), clipped to −3.5/+2.0. `a_target` is read from the plan at
  `longitudinalActuatorDelay + DT_MDL` = 0.55 s on Honda Bosch.
- **MPC costs fixed**: X_EGO_OBSTACLE 3, J_EGO 5, A_CHANGE 200, DANGER_ZONE 100; COMFORT_BRAKE 2.5,
  STOP_DISTANCE 6. Lead prediction `a_lead·exp(−aLeadTau·t²/2)`.
- **Longcontrol**: feedforward + integral; Honda Bosch never overrides `kiV = [0.]`, so output = `a_target`.
  Stopping ramps to `stopAccel` (−2.0 default) at a fixed 1.0 m/s³.
- **radard**: 1-D KF on `vLead` at `DT_MDL`; `_LEAD_ACCEL_TAU` 1.5; Laplacian vision-radar match.
- **Honda Bosch opendbc**: `ACCEL_COMMAND = clip(accel, −3.5, 2.0)`; gas lookup from −0.2; brake request
  below −0.2; `longitudinalActuatorDelay` 0.5, `radarDelay` 0.1. **No accel or jerk rate limit on Bosch.**

### 12.2 Upstream vs this fork (HEAD)

| Area | Upstream | This fork |
|---|---|---|
| MPC structure | leads only; cruise/e2e as outside candidates | `acc`/`blended` modes, sources lead0/lead1/cruise/e2e (`long_mpc.py:445, 587`) |
| MPC costs | fixed 3 / 5 / 200 | speed-scheduled (`X_EGO_OBSTACLE_COSTS` [3,3,2.5,2] etc.), lead filter times, far-lead accel taper |
| Cruise decel / jerk | −1.2, explicit 0.6-1.6 m/s³ | −1.0 (`longitudinal_planner.py:775`), inside the MPC |
| Plan read-off | 0.55 s | `PLANNER_ACTION_T_S` 0.30 (D-072, replay) |
| Brake shaping | none | release-side only: `BRAKE_RELEASE_JERK` 2.5, release dwell, `COAST_CEILING_JERK` 2.5 |
| `_LEAD_ACCEL_TAU` | 1.5 | 0.6 (`radard.py:22`) |
| radard KF step | DT_MDL | 1/14.35 s; `aLeadTau` still DT_MDL (§10.2) |
| vRel | raw radar `vRel` | U11 + one-sided range-derived assist (D-041/043/044/053/074) |
| `radarDelay` (Honda) | 0.1 (ego history in DT_MDL steps) | 0.1; history appended at 20 Hz, so 0.1 s effective — but unmeasured for Bosch-A (§10.2) |
| Bosch command | clip; gas from −0.2 | clip; gas from 0.0; pitch, wind, learned gas factor, braking hysteresis. No brake-side rate limit, no over-delivery compensation |

### 12.3 Proposals for smoother braking that use the Bosch-A radar fully

Ordered by what each needs first. Every one: toggle-gated, A/B on closed-loop replay
(`tools/longitudinal/alpha_closed_loop_replay.py`) over the D-072 route set, then limited road evidence.
Read each constant's evidence block before changing it (CLAUDE.md rule 5).

**P0 — Measure the plant first.** Log `ACCEL_COMMAND`, `aEgo`, `aEgoVsa` (§11.1) and the wheel
derivative side by side; fit command → delivered accel (lag, gain, onset jerk) binned by speed and
grade; add that plant to the closed-loop replay. Everything below depends on it.

**P1 — Range-first lead kinematics (largest expected gain).** The fork's own evidence says U11 is
the *slower* channel: it sees closing onset 0.88-1.28 s late (D-043/D-044) and saturates at −12/−13.5
m/s (D-041, D-074), while range is Q7-exact at 14.35 Hz. Replace the per-track 1-D KF with a 3-state
(x, v, a) filter whose primary measurement is range, with U11 as a delayed secondary measurement with
large R near the rail and in transients; derive `aLeadK` from it. Keep the one-sided bound semantics —
it may only *add* braking evidence (D-042). Expected: lead braking recognised ≈ 1 s earlier, so the
planner can brake earlier and softer instead of later and harder. Risk: ~1 % gross range outliers
(`radard.py:27`) and range walks (route 232 3:02.8) need innovation gating, or a false closing becomes
a phantom brake. Validate with `tools/bosch_a_corpus_report.py` residuals vs `vRelRangeDerived`
(D-044), the D-049 track-ID lifecycle audit, the D-041/D-053 cases, then shadow on the road.

**P2 — Fix the `aLeadTau` timebase and re-decide `_LEAD_ACCEL_TAU`** (§11.3). A tau of 0.6 makes the
MPC assume a braking lead keeps braking; on lead-brake-then-release events that is over-brake followed
by a release, which is felt as jerk. Risk: a longer tau anticipates a genuinely hard-braking lead less.

**P3 — Time-aligned ego reference for `vLead`** (§11.2). Removes ego-accel leakage from `aLeadK`,
which today is d/dt(vRel + vEgo) with a 0.1 s delay that was never measured for this radar.

**P4 — Over-delivery compensation, comfort band only — after P0.** If P0 confirms the ≈ 27 %
over-brake against `aEgoVsa` too, add `cmd = desired + k(desired)` only for about −1.0 to −3.0 m/s²,
|k| ≤ 0.3, and **never** in the −3.0…−3.5 band (item 71 option 3). A command-neutral alternative: when
delivered accel (`aEgoVsa`) and the planned accel diverge by more than 0.3, seed the MPC with the
delivered value so it stops stacking extra decel on an over-delivering plant. Risk: less braking at
the hard end if the band leaks; the effect is likely grade- and speed-dependent.

**P5 — Coast first, then soft brake, for far radar leads.** Merge `FAR_LEAD_COAST_*` and
`VEHICLE_FAR_FOLLOW_SLEW_*` into one ladder for radar leads at 60-150 m with TTC > 8 s: drop throttle,
then cap at −0.3…−0.8 m/s² with 0.5-1.0 m/s³ onset, then hand to the unconstrained MPC below TTC ≈ 6 s.
This uses the Bosch-A radar's long range, which vision cannot match. Risk: a stale or false far track
causes phantom coasting; interacts with existing gates.

**P6 — Stop-and-go terminal soften.** Target −0.5…−0.8 m/s² in the last ≈ 1 m/s, then hold, and align
the `STANDSTILL` handshake with `stopping_counter`. STATUS item 72's two worst low-speed jolts
(258 63:50, 2882 s) are in this regime. Keep `STANDSTILL_STOPPED_LEAD_GUARD_*`.

**P7 — Lead uncertainty may only add caution.** Publish KF covariance and track age; while uncertain,
increase follow time or bias stop distance toward braking. Never shrink `aLeadK` toward 0 (D-041/D-042).

**Not proposed: a brake-onset jerk limit on the sent command.** The firmware's −5 m/s³ limiter makes
it tempting, but STATUS item 72 (replay, 79 onsets) found over-brake does not grow with onset rate, and
D-072 recorded min-gap costs (6.0 → 5.6 m) from a smaller onset delay. Only the logging in §11.5.

**Longer term (P8):** consider upstream's structure (lead-only MPC, jerk-limited cruise and coast
outside it). Very large; the whole gate stack would need re-validating on the full replay corpus.

## 13. Topics the original report did not address

The firmware work above covers the ACC/brake chain. It says nothing about the radar *track* output
that openpilot's Bosch-A parser consumes. Those items stand on their own evidence, summarised here.
File/line references are to HEAD `6fd6eed`.

### 13.1 Track messages (the Bosch-A bank, not 0x400/0x430-0x445)

- **Layout:** 16 slots. Main frames at 0x280 + 4s for s < 4, else 0x2D0 + 4(s − 4), four frames each;
  aux frames at 0x2C8 + s for s < 8, else 0x290 + (s − 8) (`radar_interface.py:21-56`). The IDs
  0x400 / 0x430-0x445 that the cross-check §4 names belong to the **Nidec** parser
  (`radar_interface.py:14`). Hand-written DBC with 80 `BO_`.
- **Fields:** f0 STATUS, RANGE_RAW 23|12, AZIMUTH_RAW 39|11, RANGE_SIGMA; f1 EXIST_PROB 46|7,
  ANGULAR_WIDTH 23|11; f2 LIFECYCLE 7|12 (+2 per frame, saturates at 0xFFE, route 00000232),
  NORMALIZED_CLOSING 23|10 (1/64, −8); f3 azimuth edges A/B; aux U11 7|11, u10 23|10, RANGE_RATIO 55|10.
- **Evidence:** range scale, azimuth scale and range-ratio normalisation are firmware-exact (static);
  lifecycle, the U11 sentinel 0x7FE and the rails 0/1728 are capture-based (replay).
- **Open:** the firmware descriptor name for U11; the track-ID lifecycle (D-049).
- **Suggested firmware trace:** find the TX descriptors for 0x280-0x2DF in the same CanIf tables the
  cross-check used (0x1592xx / 0x159fxx) and the signal table at 0x162604, as was done for 0x1DF in §8.3.
  That would name every field and settle U11's unit.

### 13.2 U11 speed scale (1/72)

- **Decision:** D-074, accepted (`radar_interface.py:176`).
- **Static:** a sibling camera firmware (36161-TLA-A070) holds the f32 0x3c638e45 = 1/72.
- **Replay:** GPS-stationary targets give 70.75; lead stops 71.55 [71.26, 72.40]; approaches 70.90; all
  exclude 64.
- **Open:** moving-lead fits against range rate scatter over 55-70 (one job gave 66.8-77.0),
  unresolved. The owner's camera (36161-TBA-A130) has not been imaged.
- **New from this report:** none directly. §11.4 suggests testing whether ego acceleration or ego lag
  explains the moving-lead band before anyone touches the scale.
- **Suggested firmware trace:** in the radar image, locate the scaling applied to the aux-frame U11
  field before TX, as was done for KINEMATICS (float table 0x16661c).

### 13.3 Azimuth

- **Decode:** (raw − 1024)/2048, closed by the f3 edge pair (`radar_interface.py:102-109`);
  `yRel = dRel·tan(az)` (`:370, :953`).
- **Evidence:** sign confirmed on the road 2026-08-22 (limited road evidence).
- **Open:** tan vs sin (the unit may be a sine of the angle); mount yaw offset.
- **Suggested firmware trace:** the azimuth's TX scaling, and any mount-alignment constant in
  calibration data.

### 13.4 Range scale and offset

- **Scale:** 1/16 m, firmware-exact (`radar_interface.py:60-71`).
- **Offset:** −3.0 m (`:78`), with a per-unit calibration path and a −2.617 m fallback (unit 335).
  D-076 proposes the toggle default off (+0.383 m, less conservative).
- **Open:** neither offset has been measured on this car; a laser check is planned.
- **Suggested firmware trace:** the calibration-block read that produces the offset, to say whether
  it is per-unit (EOL) or a constant.

## Revision log

Revision 3 — 2026-10-04 (static):

- **a.** §10.2/§11.2/§12: `v_ego_hist` is appended at the 20 Hz radard loop (modelV2 poll), so the effective ego
  delay is the configured 0.1 s, not ≈ 0.14 s. P3 is now "measure the sweep latency", not "fix the timebase".
- **b.** The `aLeadTau` claim stands: it is stepped with `DT_MDL` only on fresh Bosch-A sweeps (≈ 14.35 Hz).
  A default-off radard flag, `BOSCH_A_LEAD_ACCEL_TAU_RADAR_DT`, now steps it with the radar period (unit tests only).
- **c.** Offline tool `tools/longitudinal/bosch_vsa_accel_report.py` added for P0 and §11 items 1/4.

Revision 2 — 2026-10-04 (all static; firmware-trace items carried from the 2026-10-03 cross-check, not re-run):

- **a.** Input b re-identified: COM 0x276 = KINEMATICS 0x094 `LONG_ACCEL` (VSA measured accel), not a radar/cruise
  demand; `0xd0c58` = min of two measured ego-acceleration estimates; the original "actual vs target" / "demand" wording is kept
  and annotated inline with a pointer to this note; meaning for the rate limiter is an open hypothesis.
- **b.** 0x274 "companion validity" unproven (1-bit field, LSB 52 of 0x094); 0x14366c branch sense reversed (clear
  runs when byte == 1).
- **c.** 0x2b6..0x2b9 = 0x1D0 WHEEL_SPEEDS confirmed (PDU 110, 4/4 signals; readers 0x144988..0x144a04).
- **d.** 0x72d4e is `e_sth r3,-0x18(r13)`; /5 quotient in r12; v_ref store claim unsupported.
- **e.** §8.1: 0xdf450 rA = 0, 4-byte gap 0xdf444→0xdf44c, 0xdf454 `e_bl` → 0xbb20c; listing unreliable.
- **f.** 0xd0c58 body is 90 bytes (0x5a), not 88.
- **g.** 0x1DF table: COUNTER 61|2, CHECKSUM 59|4, ACCEL_COMMAND bits 31..24 + 39..37 (LSB 37), GAS_COMMAND start
  7 / LSB 8; firmware TX descriptor ids added; five omitted DBC signals listed.
- **h.** IIR time constants ~8.0 s / ~1.6 s and dead bands 400 / 80 Q11 counts; flagged implausible, needs
  re-trace.
- **i.** §6.4 "-10 counts" is CAN 0.01 units = -205 Q11 counts.
- **j.** `iselgt` "max" at 0xd0bba / 0xd0bd8 unproven (compare not printed).
- **k.** `1909c801` / `180ad0c0` operand order reversed (cosmetic).
- **l.** Bosch-A parser reads 0x280-0x283 / 0x2D0-0x2FF + aux 0x2C8-0x2CF / 0x290-0x297, not 0x400/0x430-0x445
  (Nidec); reads neither 0x1DF nor 0x094.
- **m.** Sections 10-13 added: check against this repo's radard / planner / Bosch command path at HEAD `6fd6eed`;
  parser and radard improvements; upstream openpilot (`ec95db3f`) / opendbc (`35f7e081`) comparison and braking
  proposals; evidence status of the track decode, U11 1/72 scale, azimuth and range scale/offset, which the
  original did not cover. All static or carried replay evidence; all proposals unvalidated.
