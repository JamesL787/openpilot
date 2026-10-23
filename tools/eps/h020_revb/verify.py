#!/usr/bin/env python3
"""Independent offline structure/byte-diff checks and strict execution of actual H020 ROM functions."""

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import struct

if __package__:
  from .rwd_codec import DECRYPT
  from .sh2a import CPU, s32
else:
  from rwd_codec import DECRYPT
  from sh2a import CPU, s32

if not __debug__:
  raise RuntimeError("verification must run with Python assertions enabled")

ROOT, SCR, ROW = 0xFFF879A8, 0xFFF8E000, 0xFFF87B40
MAP_X, MAP_Y, P_X, P_Y, D_X, D_Y = 0x13794, 0x13812, 0x13AE2, 0x13B60, 0x139E6, 0x13A64


def w(data, address, count=9):
  return struct.unpack_from(f'>{count}H', data, address)


def tz(a, b):
  return (-1 if a < 0 else 1) * (abs(a) // b)


def clip(x, lo, hi):
  return min(hi, max(lo, x))


def fraction_interp(x, xs, ys):
  if x <= xs[0]:
    return Fraction(ys[0])
  for i in range(1, len(xs)):
    if x <= xs[i]:
      return Fraction(ys[i - 1]) + Fraction((x - xs[i - 1]) * (ys[i] - ys[i - 1]), xs[i] - xs[i - 1])
  return Fraction(ys[-1])


def rom_interp(x, xs, ys):
  if x <= xs[0]:
    return ys[0]
  for i in range(1, len(xs)):
    if x < xs[i]:
      return clip(ys[i - 1] + tz((x - xs[i - 1]) * (ys[i] - ys[i - 1]), xs[i] - xs[i - 1]), -32767, 32767)
  return ys[-1]


def parse_independent(raw):
  assert raw[:3] == b'Z\r\n'
  fields = []
  i = 3
  for _ in range(6):
    count = raw[i]
    i += 1
    field = []
    for _ in range(count):
      n = raw[i]
      i += 1
      field.append(raw[i : i + n])
      i += n
    fields.append(field)
  start = int.from_bytes(raw[i : i + 4], 'big')
  length = int.from_bytes(raw[i + 4 : i + 8], 'big')
  i += 8
  assert len(raw) == i + length + 4
  assert int.from_bytes(raw[-4:], 'little') == sum(raw[:-4]) & 0xFFFFFFFF
  return fields, start, bytes(DECRYPT[v] for v in raw[i : i + length])


def fresh(image, row):
  cpu = CPU(image)
  cpu.set8(ROW, row)
  cpu.set32(0xFFF87A9C, SCR)
  cpu.set32(0xFFF87AB0, SCR + 0x100)
  cpu.set32(0xFFF87B34, SCR + 0x200)
  return cpu


def execute_curve(cpu, q, entry=0x29746):
  cpu.set16(SCR + 8, q)
  cpu.call(entry)
  return cpu.get16(SCR + 0x106)


def model_curve(image, row, q):
  mag = rom_interp(min(abs(q), 1663), w(image, MAP_X + 18 * row), w(image, MAP_Y + 18 * row))
  return mag if q > 0 else -mag if q < 0 else 0


def model_pd(image, row, q, target, reference, previous_error):
  err = target - reference
  delta = clip(err - clip(previous_error, -65536, 65536), -65536, 65536)
  x = abs(max(q, -32767))
  p = clip(tz(rom_interp(x, w(image, P_X + row * 18), w(image, P_Y + row * 18)) * err, 1024), -7373, 7373)
  d = clip(tz(rom_interp(x, w(image, D_X + row * 18), w(image, D_Y + row * 18)) * delta, 1024), -1774, 1774)
  return clip(p + d, -32767, 32767), p, d, err


def structural(image, rwd, parent, stock, reference, clarity, response):
  fields, start, payload = parse_independent(rwd)
  assert start == 0x4000 and len(payload) == 0x4C000 and payload == image[0x4000:0x50000]
  assert len(image) == 0x80000 and image[:0x4000] == stock[:0x4000] and image[0x50000:] == stock[0x50000:]
  assert fields[:3] == [[b'\0'], [], [b'\x30']] and fields[5] == [b'\x01\x02\x03']
  assert [v.rstrip(b'\0') for v in fields[3]] == [b'39990-TEA-H020', b'39990-TEA,H020', b'39990-TEA,H02B']
  assert len(fields[4]) == 3 and all(key == stock[0x551E4:0x551EA] for key in fields[4])
  assert sum(int.from_bytes(image[i : i + 2], 'big') for i in range(0x4000, 0x50000, 2)) & 0xFFFF == 0
  assert int.from_bytes(image[0x4FF80:0x4FF82], 'big') == sum(int.from_bytes(image[i : i + 2], 'big') for i in range(0x4000, 0x4FF80, 2)) & 0xFFFF
  assert w(image, 0x4000, 1) == (0x4837,) and (w(image, 0x4000, 1)[0] + w(image, 0x4FFFC, 1)[0]) & 0xFFFF == 0xFFFF
  target_x, target_y, target_px, target_py = (0x13798, 0x13816, 0x13AE6, 0x13B64) if response == 'tgg' else (0x13810, 0x1388E, 0x13B5E, 0x13BDC)
  rx, ry = w(reference, target_x), w(reference, target_y)
  allow = {0x4FF80, 0x4FF81, 0x4FFFE, 0x4FFFF}
  for row in range(6):
    xs = w(parent, MAP_X + 18 * row)
    ys = [round(fraction_interp(x, rx, ry)) for x in xs]
    for i, x in enumerate(xs):
      if x > 1663:
        ys[i] = round(ys[i - 1] + (fraction_interp(1663, rx, ry) - ys[i - 1]) * Fraction(x - xs[i - 1], 1663 - xs[i - 1]))
    assert w(image, MAP_X + 18 * row) == xs and w(image, MAP_Y + 18 * row) == tuple(ys)
    assert w(image, P_X + 18 * row) == w(reference, target_px) and w(image, P_Y + 18 * row) == w(reference, target_py)
    assert w(image, D_X + 18 * row) == w(parent, D_X + 18 * row) and w(image, D_Y + 18 * row) == w(parent, D_Y + 18 * row)
    assert w(image, 0x135E4 + 18 * row) == w(clarity, 0x13660) and w(image, 0x13662 + 18 * row) == w(clarity, 0x136DE)
    for base in [MAP_Y, P_X, P_Y, 0x135E4, 0x13662]:
      allow.update(range(base + row * 18, base + row * 18 + 18))
  for base in [MAP_X, MAP_Y, P_X, P_Y, D_X, D_Y]:
    assert w(image, base + 108) == w(stock, base + 108)
    allow.update(range(base + 108, base + 126))
  for i in range(7):
    a = 0x4B459 + i * 0x59
    assert image[a : a + 14] == b'39990-TEA,H02B'
    allow.update(range(a, a + 14))
  changed = {i for i, (a, b) in enumerate(zip(image, parent, strict=True)) if a != b}
  assert changed <= allow and all(0x4000 <= i < 0x50000 for i in changed)
  assert w(image, 0x13890, 3) == w(clarity, 0x1390C, 3) == (7373, 1774, 9000)
  assert w(image, 0x2A70E, 3) == (0, 1650, 0x4680)
  return {
    'RWD_round_trip_and_header': True,
    'both_application_checksums': True,
    'exact_declared_table_edits': True,
    'native_command_axes_preserved': True,
    'row6_stock': True,
    'Clarity_limits': True,
    'boot_loader_and_code_unchanged': True,
    'changed_bytes': len(changed),
  }


def loader_checks(image):
  c = CPU(image)
  c.stubs[0x54744] = lambda cpu: cpu.R.__setitem__(0, 0)
  assert c.call(0x52202, args=(0x4000, 0x4C000)) == 0
  blocks = []
  for address in [0x4000, 0x4FFFF]:
    c = CPU(image)
    c.stubs[0x54744] = lambda cpu: cpu.R.__setitem__(0, 0)
    blocks.append(c.call(0x521C8, args=(address,)))
  assert blocks == [0, 9]
  for value in range(256):
    c = CPU(image)
    c.set8(SCR, (((value ^ 1) ^ 2) + 3) & 255)
    c.call(0x50A00, args=(SCR,))
    assert c.rd(SCR, 1) == DECRYPT[value]
  return {
    'range_gate_executed': '0x52202 ACCEPT',
    'block_lookup_executed': '0x521c8: blocks 0..9',
    'loader_decrypt_0x50a00_cases': 256,
    'stub': '0x54744 watchdog helper only',
  }


def execute(image, reference, response):
  rng = random.Random(20261022)
  report = {}
  comparisons = []
  reference_entry = 0x297A6 if response == 'tgg' else 0x29FB4
  ref = fresh(reference, 0)
  # Reference record/row pointers differ on Clarity; derive the two pointer literals and row byte from its command entry.
  if response == 'clarity':
    literals = []
    outoff = None
    pc = reference_entry
    while pc < reference_entry + 0x100:
      op = int.from_bytes(reference[pc : pc + 2], 'big')
      if op & 0xFFF0 == 0x5410:
        outoff = (op & 15) * 4
      if op == 0x000B:
        break
      if op >> 12 == 0xD:
        a = (pc & ~3) + 4 + (op & 255) * 4
        literals.append(int.from_bytes(reference[a : a + 4], 'big'))
      pc += 2
    assert outoff is not None
    ref = CPU(reference)
    ref.set32(literals[0], SCR)
    ref.set32(literals[0] + outoff, SCR + 0x100)
    ref.set8(literals[2], 0)
  for row in range(7):
    c = fresh(image, row)
    qs = list(range(-1800, 1801)) + [-32768, -32767, 32766, 32767]
    for q in qs:
      assert execute_curve(c, q) == model_curve(image, row, q), (row, q, 'map')
    cases = [(rng.randint(-32768, 32767), rng.randint(-32768, 32767), rng.randint(-32768, 32767), rng.randint(-100000, 100000)) for _ in range(500)]
    cases += [(q, s, r, e) for q in [-32768, -1663, 0, 1663, 32767] for s in [-30000, 0, 30000] for r in [-32765, 0, 32765] for e in [-100000, 0, 100000]]
    for q, s, r, e in cases:
      expected, p, d, err = model_pd(image, row, q, s, r, e)
      c.call(0x29AB8, args=(q & 0xFFFFFFFF, s & 0xFFFFFFFF, r & 0xFFFFFFFF, e & 0xFFFFFFFF))
      assert s32(c.R[0]) == expected, (row, 'PD', q, s, r, e)
      assert (c.get16(SCR + 0x220), c.get16(SCR + 0x21E), c.get32(SCR + 0x224)) == (p, d, err)
    # Execute real final wrapper, FF cave and A280. Isolate the unmeasured driver governor with an explicit synthetic gain.
    for _ in range(200):
      q = rng.randint(-1663, 1663)
      s = model_curve(image, row, q)
      r = rng.randint(-32765, 32765)
      e = rng.randint(-100000, 100000)
      rate = rng.randint(-1000, 1000)
      blend = rng.choice([0, 8192, 16384])
      driver = rng.choice([0, 32, 128, 256])
      c.stubs[0x298F2] = lambda cpu, g=driver: cpu.R.__setitem__(0, g)
      c.set16(SCR + 8, q)
      c.set16(SCR + 0x106, s)
      c.set16(ROOT + 0x64, r)
      c.set16(ROOT + 0x5C, rate)
      c.set16(ROOT, blend)
      c.set16(ROOT + 2, 16384 - blend)
      c.set32(SCR + 0x224, e)
      c.call(0x297C2, args=(0,))
      a = rom_interp(abs(rate), w(image, 0x13896 + 12 * row, 6), w(image, 0x138EA + 12 * row, 6))
      b = rom_interp(abs(rate), w(image, 0x1393E + 12 * row, 6), w(image, 0x13992 + 12 * row, 6))
      gain = tz(a * blend, 16384) + tz(b * (16384 - blend), 16384)
      expected = clip(tz(tz(driver * gain, 256) * clip(model_pd(image, row, q, s, r, e)[0] + ((45 * s) >> 10), -32767, 32767), 256), -9000, 9000)
      assert c.get16(SCR + 0x23A) == expected, (row, 'full wrapper', q)
    report[row] = {'map_cases': len(qs), 'PD_cases': len(cases), 'full_wrapper_cases': 200}
    print(f'row {row}: map {len(qs)}, PD {len(cases)}, wrapper 200 PASS', flush=True)
  # Compare actual executed target-map response throughout the reachable key range, independent of host interpolation.
  c = fresh(image, 0)
  for q in range(-1663, 1664):
    a = execute_curve(c, q)
    b = execute_curve(ref, q, reference_entry)
    comparisons.append(abs(a - b))
  assert max(comparisons) <= 16, ('target response differs beyond declared resampling tolerance', max(comparisons))
  return {
    'rows': report,
    'target_comparison_keys': len(comparisons),
    'max_R5_difference_counts': max(comparisons),
    'comparison_tolerance_counts': 16,
    'full_wrapper_driver_governor': 'synthetic gain; runtime shaping gates are not validated',
  }


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--inputs', type=Path, required=True)
  parser.add_argument('--candidate', type=Path, required=True)
  parser.add_argument('--response', choices=['tgg', 'clarity'], required=True)
  args = parser.parse_args()
  i = args.inputs
  manifest = json.loads((Path(__file__).parent / 'SOURCES.json').read_text())
  for name, source in manifest['inputs'].items():
    assert hashlib.sha256((i / name).read_bytes()).hexdigest() == source['sha256'], ('input hash mismatch', name)
  stock = (i / 'stock.bin').read_bytes()
  clarity = (i / 'clarity.bin').read_bytes()
  reference = (i / ('tgg-revb.bin' if args.response == 'tgg' else 'clarity.bin')).read_bytes()
  results = {}
  for tracker in [4250, 3200]:
    path = next(args.candidate.glob(f'*Trk{tracker}.full0x80000.bin'))
    rwd = next(args.candidate.glob(f'*Trk{tracker}.rwd')).read_bytes()
    image = path.read_bytes()
    parent = (i / f'parent-{tracker}.bin').read_bytes()
    static = structural(image, rwd, parent, stock, reference, clarity, args.response)
    loader = loader_checks(image)
    execution = execute(image, reference, args.response) if tracker == 4250 else {'same_code_tables_as_4250': True}
    if tracker == 3200:
      other = next(args.candidate.glob('*Trk4250.full0x80000.bin')).read_bytes()
      diffs = [n for n, (a, b) in enumerate(zip(image, other, strict=True)) if a != b]
      assert set(diffs) <= {0x1378E, 0x1378F, 0x4FF80, 0x4FF81, 0x4FFFE, 0x4FFFF}
      execution['variant_difference_addresses'] = [hex(n) for n in diffs]
    results[tracker] = {
      'image_sha256': hashlib.sha256(image).hexdigest(),
      'rwd_sha256': hashlib.sha256(rwd).hexdigest(),
      'structural': static,
      'loader': loader,
      'execution': execution,
    }
  (args.candidate / 'VERIFICATION.json').write_text(json.dumps(results, indent=2) + '\n')
  print(json.dumps(results, indent=2))


if __name__ == '__main__':
  main()
