"""Which command-map row is live? Fit the firmware's own R5 (from 0x6A0-0x6A3 telemetry) against each row.

Usage:
  live_row_fit.py teg '<dir>/rlog*.zst'     # TEG-A010 / A030 telemetry builds (08-12, 08-26, 10-03): bus 0
  live_row_fit.py c020 '<dir>/rlog_*.zst'   # C020 telemetry builds (08-05 Trk4500, 10-03 A280 flat): bus 1
The live row tells which variant record the car carries (TEG: TEGA1 row 2, TEGA2 row 3; A030: TBCA1 row 2, TBCA2 row 3);
point the calibration's r5_key_bp / kp_key_bp at that row and mark the row 'measured' in CALIBRATION_PROVENANCE.

R5 per frame, validated 2026-10-10:
  C020: s32(0x6A1 w0:w1) (=0xFFF8A970, R5-R6) + 0x6A2 w0 (R6). Route 294: row 1 median |res| 23, row 0 178.
  TEG : s32(0x6A0 w2:w3) (pd+0x24 error) + 0x6A1 w1 (feedback). Route 00000001 on the 08-12 build: its
        stock-shaped axis median |res| 44, C020 row-1 axis 1109.
key = trunc(trunc(E4*56756/32768)/4), E4 from sendcan 0xE4, one telemetry frame of lag.
Rows below are the 08-26/10-03 TEG and 10-03 C020 key axes (identical in both images); R5 values are shared.
"""
import glob
import struct
import sys

import numpy as np
import zstandard

from cereal import log

TX = {0: (0, 99, 258, 447, 643, 862, 1111, 1549, 1774), 1: (0, 115, 254, 449, 654, 862, 1111, 1549, 1774),
      2: (0, 111, 222, 333, 499, 665, 887, 1108, 1774), 3: (0, 222, 333, 495, 656, 887, 1108, 1552, 1774)}
TY = (0, 1926, 4938, 8455, 12036, 15926, 20138, 26955, 30000)


def s16(b, i):
  return struct.unpack('>h', b[i:i + 2])[0]


def u16(x):
  return np.where(x < 0, x + 65536, x)


def load(files, bus):
  rows, e4, tel = [], None, {}
  for f in files:
    for m in log.Event.read_multiple_bytes(zstandard.ZstdDecompressor().stream_reader(open(f, 'rb')).read()):
      w = m.which()
      if w == 'sendcan':
        for c in m.sendcan:
          if c.address == 0xE4:
            e4 = s16(c.dat, 0)
      elif w == 'can':
        for c in m.can:
          if c.src == bus and 0x6A0 <= c.address <= 0x6A3 and len(c.dat) == 8:
            tel[c.address] = [s16(c.dat, 2 * i) for i in range(4)]
            if c.address == 0x6A3 and len(tel) == 4 and e4 is not None:
              rows.append([e4] + tel[0x6A0] + tel[0x6A1] + tel[0x6A2] + tel[0x6A3])
  return np.array(rows, float)


def main(car, pattern, lag=1):
  A = load(sorted(glob.glob(pattern)), 0 if car == 'teg' else 1)
  W = A[:, 1:]
  r5 = (W[:, 2] * 65536 + u16(W[:, 3]) + W[:, 5]) if car == 'teg' else (W[:, 4] * 65536 + u16(W[:, 5]) + W[:, 8])
  k = np.trunc(np.trunc(A[:, 0] * 56756 / 32768) / 4)
  k = np.r_[np.zeros(lag), k[:-lag]]
  ka, r5 = np.clip(np.abs(k), 0, 1774), r5 * np.sign(k)
  ok = ka > 20
  print(f'{len(A)} frames, {ok.sum()} with |key| > 20')
  for a, b in zip([20, 60, 100, 140, 180, 220, 260, 320, 400, 500, 650, 850], [60, 100, 140, 180, 220, 260, 320, 400, 500, 650, 850, 1100], strict=True):
    m = ok & (ka >= a) & (ka < b)
    if m.sum() >= 100:
      print(f'  key {a:4d}-{b:<4d} n={m.sum():6d} measured {np.median(r5[m]):7.0f} | ' +
            '  '.join(f'row{r} {np.median(np.interp(ka[m], TX[r], TY)):6.0f}' for r in TX))
  for r in TX:
    print(f'row {r}: median |R5 - map| {np.median(np.abs(r5[ok] - np.interp(ka[ok], TX[r], TY))):.0f}')

if __name__ == '__main__':
  main(sys.argv[1], sys.argv[2])
