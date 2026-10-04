# Cross-check vs openpilot-radar (opendbc DBC + Honda radar parser) — 2026-10-03

> **Folded in 2026-10-04 from an attached PDF** (4 pages, sha256
> `e18c49d2f9a13f2727c12729fae55e014c9175b8b86216809b931bcdd8d2ec7b`; the PDF itself is not committed).
> Transcribed faithfully below; the paths it names (`~/openpilot-radar`, `radar-re/…`, the `xcheck_*.py` scripts)
> are on the author's machine, not in this repo.
>
> **Verification notes by the receiving session:**
>
> 1. §1 / §3 DBC facts (KINEMATICS 0x094 `YAW_RATE 7|10`, `LONG_ACCEL 24|9@0-` factor -0.049; 0x1D0
>    WHEEL_SPEEDS; 0x1DF ACC_CONTROL `ACCEL_COMMAND 31|11@0-` (0.01), `GAS_COMMAND 7|16@0-`, `BRAKE_REQUEST 34`,
>    `AEB_PREPARE 43`, `AEB_STATUS 33`, `STANDSTILL 35`, `STANDSTILL_RELEASE 36`, `BRAKE_LIGHTS 62`) re-checked
>    against the opendbc DBCs in this repo: **confirmed** [CONFIRMED static: opendbc DBC].
> 2. Offset-binary vs two's-complement equivalence: the firmware reads 0x276 as 10 bits (LSB 32, MSB 25) unsigned,
>    `raw*0.0478515625 - 24.5` (offset binary centred at 512), then negates; opendbc reads 9 bits signed (MSB 24),
>    factor -0.049. For |value| < 256 counts the low 9 bits of the offset-binary field equal the 9-bit two's
>    complement, so both read the same window and sign; the scales differ by 2.4%. **Confirmed** (static arithmetic).
> 3. §4 mislabels `0x400`, `0x430-0x439`, `0x440-0x445` as the "Bosch-A bank" — those are the **Nidec** parser's
>    IDs. The Bosch-A parser in `opendbc_repo/opendbc/car/honda/radar_interface.py` reads the 16-slot bank
>    0x280-0x283 / 0x2D0-0x2FF (4 frames per slot) plus aux 0x2C8-0x2CF / 0x290-0x297. The conclusion still
>    holds: neither parser reads 0x1DF or 0x094.
> 4. The COM / CanIf table traces (§1, §2, §3 firmware columns) are **not re-runnable here**: the firmware image
>    `36802TBA.dec.bin` and the `xcheck_*` / `sigtable_*` scripts are not in this repo. They are carried as
>    [FIRMWARE TRACE by xcheck 2026-10-03, not re-run here].

---

**Scope:** check the claims in `acc_brake_notes.md`, `audit_report.md` and `honda_bosch_acc_brake_internals.md`
against `~/openpilot-radar` (opendbc_repo DBCs, `car/honda/radar_interface.py`, `STATUS.md` / `FINDINGS.md`). All
firmware facts below come from `radar-re/36802TBA.dec.bin` via the scripts named; nothing is taken from the three
documents on trust.

## Verdict up front

**The identity of input b is wrong in all three documents.** COM signal `0x276` is not a radar/cruise
"longitudinal demand". It is **`LONG_ACCEL` in CAN `0x094` KINEMATICS**, the VSA's measured longitudinal
acceleration. So `0xd0c58` computes **min(a, b) of two measured ego-acceleration estimates**: the wheel-speed
derivative (`a`) and the VSA accelerometer (`b`). It is not "actual vs target".

The arithmetic (signed min, Q11, negation, 5-tap mean, ceiling clamp) still stands. The meaning built on top of it
does not.

## 1. COM RX handle → PDU → CAN ID (new, independent)

`Com_ReceiveSignal` `0x14a6c4` indexes signal descriptors at `0x162604 + 12*h` (`+8` = PDU index, `+6` = bit
length, `+7` = LSB start bit). Script: `xcheck_com_handles_2026-10-03.py`.

| handle | PDU | len | LSB |
|---|---|---|---|
| `0x2b6..0x2b9` | 110 | 15 | 60 / 43 / 26 / 9 |
| `0x276` | 105 | 10 | 32 |
| `0x278` | 105 | 10 | 14 |
| `0x274` | 105 | 1 | 52 |

**Layout fingerprint vs opendbc** (`xcheck_pdu_fingerprint_2026-10-03.py`, Motorola MSB→LSB converted):

- PDU 110 matches `0x1D0` WHEEL_SPEEDS on all 4 signals (RR/RL/FR/FL). This is the control case and it passes.
- PDU 105: `0x278` (LSB 14, 10 bit) = `KINEMATICS.YAW_RATE 7|10`. `0x276` (LSB 32) lands on
  `KINEMATICS.LONG_ACCEL 24|9`. The firmware reads it as 10 bits (MSB 25) where opendbc uses 9 bits (MSB 24). The
  window is the same.

**PDU→CAN-ID table** (`xcheck_canid_table_2026-10-03.py`): two separate CanIf tables (stride 20 at `0x1592xx`,
stride 16 at `0x159fxx`) both list PDU 105 = `0x094` and PDU 110 = `0x1D0`. Their neighbours are plausible Honda
IDs (`0x296`, `0x1a3`, `0x1a4`, `0x1b0`, `0x18dbbff1` UDS functional).

**Scale/sign agree with opendbc:** the firmware float table `0x16661c` gives `raw*0.0478515625 - 24.5` (= 49/1024
per count) and the result is then negated by `0x9c308`. opendbc defines `LONG_ACCEL` with factor `-0.049`. The
magnitudes agree to 2.4%, and the negative sign in the DBC explains why the firmware negates. So **b =
forward-positive measured acceleration in Q11.**

## 2. Input a (wheel speeds) — confirmed at the COM boundary

The documents' claim that `0x2b6..0x2b9` = `0x1D0` wheel speeds is confirmed (§1). Readers are at
`0x144988..0x144a04`. I did not re-trace the 5-tap mean, differentiator or IIR chain today; those rest on
`audit_report.md`.

## 3. CAN 0x1DF ACC_CONTROL TX side — confirmed

Firmware TX descriptors (`sigtable_2026-10-02.py`: `[+4]` = len, `[+5]` = LSB) vs `_bosch_radar_acc.dbc`:

| fw id | len/LSB | DBC | ok |
|---|---|---|---|
| `0x0a` | 11 / 37 | `ACCEL_COMMAND 31 11@0- (0.01)` → LSB 37 | ✓ |
| `0x14` | 16 / 8 | `GAS_COMMAND 7 16@0-` → LSB 8 | ✓ |
| `0x11` | 1 / 34 | `BRAKE_REQUEST 34` | ✓ |
| `0x1d` | 1 / 43 | `AEB_PREPARE 43` | ✓ |
| `0x10`, `0x17`, `0x0f`, `0x1e` | 1 / 33, 35, 36, 62 | `AEB_STATUS`, `STANDSTILL`, `STANDSTILL_RELEASE`, `BRAKE_LIGHTS` | ✓ |

Notation errors in `honda_bosch_acc_brake_internals.md`: "GAS_COMMAND bit 8" is the LSB (the DBC start bit is 7).
"Packed into bits 31-21" is wrong for Motorola order: the bits are 31..24 then 39..37.

## 4. Honda radar parser (`radar_interface.py`)

The parser only consumes track output (`0x400`, `0x430-0x439`, `0x440-0x445`, Bosch-A bank). It reads neither
0x1DF nor 0x094, so it cannot confirm or refute anything in the brake chain. There is no conflict.

> **Receiving-session note (2026-10-04):** the IDs listed here are the Nidec parser's, not the Bosch-A bank. The
> Bosch-A parser reads 0x280-0x283, 0x2D0-0x2FF (16 slots, 4 frames each) and aux 0x2C8-0x2CF / 0x290-0x297.
> Neither path reads 0x1DF or 0x094, so the conclusion stands. [CONFIRMED static: radar_interface.py]

## 5. openpilot-radar empirical findings (STATUS.md items 71-72)

- On Honda Bosch the brake ECU closes the loop on `ACCEL_COMMAND`: openpilot has no long PID on Bosch, and the sent
  value equals `actuators.accel` (p1/p99 ±0.03). This fits the firmware: the radar emits an acceleration request
  plus `BRAKE_REQUEST`, and the hydraulic control happens downstream in the VSA.
- Measured over-delivery in the -3.0…-3.6 bin (-0.25…-0.65 m/s²) is a VSA-side behaviour. It is outside this
  firmware.
- None of the existing findings identified 0x094 as an input to the radar's ACC law. That link is new here.

## 6. What must change in the three documents

1. Replace "Radar Demand / longitudinal cruise demand / external demand" for `b` with **VSA measured longitudinal
   acceleration (`KINEMATICS 0x094 LONG_ACCEL`)**.
2. `0x274` is a 1-bit field at LSB 52 of `0x094`. "Companion validity" is unproven, because opendbc has no signal
   there.
3. Re-read `0xd0c58` as `min(wheel-derived accel, accelerometer accel)`, clamped by `cfg[0x1c]/[0x18]` and fed to
   `G+0x6`. The "safety min-select against target deceleration" reading in my notes is wrong. What this bound means
   for the rate limiter (e.g. anchoring the command ceiling to measured accel) is an open hypothesis, not proven.
4. `audit_report.md` marked "b — COM 0x276" as FACTUAL. The trace is right but the label is wrong. Its PARTIALLY
   FLAWED verdict on my notes is right, for one more reason than it gave.

## Reproduce

```sh
python3 xcheck_com_handles_2026-10-03.py
python3 xcheck_pdu_fingerprint_2026-10-03.py 110 <opendbc>/dbc/honda_*generated.dbc
# control
python3 xcheck_pdu_fingerprint_2026-10-03.py 105 <opendbc>/dbc/honda_*generated.dbc
python3 xcheck_canid_table_2026-10-03.py
python3 sigtable_2026-10-02.py
```
