# EPS firmware images (`.rwd`)

Honda/Acura EPS firmware files for use with `eps-update.py` (in the repo root).
All files here were checksum-validated with `check_rwd.py` (file checksum +
decrypted firmware checksums all PASS).

Each model is kept as a **stock + linear-max pair** — `stock` is the factory
recovery image (flash this back if a flash fails), `linear-max` is the
max-torque-table mod.

## Validate
```bash
python3 check_rwd.py rwd/<file>.rwd       # single
python3 check_rwd.py rwd/*.rwd            # all
```

## Flash (see ../README.md and ../eps-update.py)
Prefer the guided flasher: `python3 flash.py` (auto-detects bus, offers dry run).
For the manual path, always run a `--danger`-less dry run first (it stops before
erase; default bus is **1**), and flash from a persistent copy — the comma updater
wipes untracked files from `/data/openpilot`. Some cars lock security access after
a dry run; wait / power-cycle before `--danger`, or use `flash.py`'s skip/retry.

## Contents
| model | stock | linear-max |
|-------|-------|-----------|
| Honda CR-V 5G (39990-TLA-A040) | `39990-TLA-A040-stock.rwd` | `39990-TLA-A040-linear-max.rwd` |
| Honda Civic (39990-TBA-C120) | `39990-TBA-C120-stock.rwd` | `39990-TBA-C120-linear-max.rwd` |
| Honda Insight (39990-TXM-A040) | `39990-TXM-A040-stock.rwd` | `39990-TXM-A040-linear-max.rwd` |

### Tuning images (rule 4 — testing fork only, not for upstream)

`39990-TLA-A040_tq30000_a9000_44256c0b.rwd` — CR-V 5G rate-authority tune,
2026-07-31. Not a linear-max variant; it changes the **controller**, not just the
torque table:

| | |
|---|---|
| feedback norm (`0x429A0`) | 1645 — stock 3429, **2.08× rate authority** |
| D-term gain row 0 (`0x11DB0`) | `699,615,589,696,730,759,778,782,782` (stock `159…486`) |
| P-term gain row 0 (`0x11EAC`) | `100,140,180,200,205×5` (stock `33,77,150,192,203,205×4`) |
| tracker alpha (`0x11ADA`) | 1999 — **stock**, leave it there |
| clamps P/D/assist | 7373 / 1774 / 9000 |
| torque row max | `0x7530` (30000) |

Measured over one drive (~9 min, 39 corner exits) against a 42-minute baseline on
the previous tune: corner-exit residual over-turn 0.0091 → **0.0037**, settle time
238 → **102 ms**, hands-off 20–35 Hz steering-rate power 5.1% → **0.90%**, plant
gain 2.6× baseline at 3–6 m/s.

**One good drive is not "proven stable on the car" per rule 4** — this stays in the
testing fork. Known open items: 3–7 Hz column-torque energy is ~3× the old tune and
has risen with every authority increase; openpilot corner-exit reversals rose
2.6 → 2.9; 2–5 m/s still tracks at 0.70–0.89 gain.

⚠ **Raising `tracker alpha` on top of this D value produced a sustained ~29 Hz
hands-off limit cycle** (±150 deg/s, 83% of steering-rate power). Alpha stays stock.

## Upstreaming guidelines

Rules for adding `.rwd` files to this branch / upstreaming them:

1. **Every file must validate.** It has to pass `check_rwd.py` (file checksum +
   decrypted firmware checksums) before it can be added.
2. **A stock `.rwd` may be added on its own.** Factory/recovery images are always
   welcome — more recovery coverage is strictly good.
3. **A linear-max (or any modified) variant may NOT be added alone.** It must be
   accompanied by a valid, verified **stock** `.rwd` for the same model, so there
   is always a factory image to flash back if a flash fails. No stock → no mod.
4. **Keep experimental work in a testing fork.** Anything still being tested or
   tuned (filter/rate variants, gain experiments, `*-test`, version-bumped
   tuning images, etc.) stays in a testing fork until it is proven stable on the
   car. Only stock images and stabilized linear-max variants belong here.
