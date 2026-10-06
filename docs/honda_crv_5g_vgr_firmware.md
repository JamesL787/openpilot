# Honda CR-V 5G `39990-TLA-A040` position VGR table

This file folds the relevant steering-table evidence from the separate Honda firmware
repository into this working tree. The external copy is now redundant for this OpenPilot
change, but was not deleted.

## Provenance

- Stock RWD: `eps_tools/rwd/39990-TLA-A040-stock.rwd`
  - SHA-256 `f84968c6b2b1fbba8b0d538b80a1782213186f92f2fc706be8eece485cb717d1`
  - flash block `0x4000..0x6ffff`
  - RWD checksum and both decrypted firmware checksums pass
- Modified RWD: `eps_tools/rwd/39990-TLA-A040_tq30000_a9000_44256c0b.rwd`
  - SHA-256 `ac6dce68bc3c36e7fa990170f7f56df678f9edd92617fd62cdf74a3e7274bc42`
- Prior OpenPilot implementation: commit `2f1f2aadef649c3c8c3ae1582ce26bb6cb259a50`
  (`Honda CR-V 5G: use firmware VGR curve`). Its rounded 30-point gain curve is
  reproduced by the exact words below.

## Static trace

The checksum-valid stock image contains a four-pointer literal block at `0x1e14c`:

```
0x11338  position (A) divisor Y
0x11374  position (A) raw-angle X
0x113b0  rate (B) divisor Y
0x113ec  rate (B) raw-angle X
```

This is the same two-lookup mechanism already traced for the related Honda images:
the A result divides steering position, while B divides the separate rate input. Table B
must not be used as a position curve. The A arrays are identical in the stock and modified
CR-V images, so the controller/torque modifications did not alter steering geometry.

The exact big-endian u16 A arrays are:

```
X = 0,42,84,125,167,209,251,292,335,419,636,864,1102,1227,1276,1326,
    1376,1426,1476,1526,1578,1628,1680,1729,2108,2488,2869,3248,3626,5130
Y = 16783,16783,16790,16795,16979,16979,17100,17086,17100,17110,17300,
    17597,17964,18170,18247,18322,18378,18460,18521,18566,18651,18697,
    18761,18803,19129,19345,19527,19657,19756,19989
```

`steer_ratio.py` reproduces the firmware position conversion as
`raw * 2**14 / divisor`. The table is selected only for the exact normalized EPS
identifier `39990-TLA-A040`; A030, A110, and A220 deliberately remain unmapped.

## Verification boundary

`[CONFIRMED static]` The arrays, addresses, stock/modified equality, and exact firmware
selection are verified from the two content-addressed images and deterministic unit tests.
This does not verify the changed requested angle on a live CR-V, real steering timing, or
the closed loop. `NrdrLatUseFirmwareVgr` remains default off, so adding the profile does not
change the default road-measured curve.
