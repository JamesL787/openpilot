#!/usr/bin/env python3
"""Build an OFFLINE H020 rev-b candidate from hash-pinned original inputs. Never flashes anything."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

if __package__:
  from .rwd_codec import encode, parse
else:
  from rwd_codec import encode, parse

START, END = 0x4000, 0x50000
OLD_VERSION, NEW_VERSION = b'39990-TEA,H020', b'39990-TEA,H02B'
STOCK_SHA = 'f169e2cd8af9d2bc055eb7f44686530c54cb466fbebc03b62a671c423dedc547'
CLARITY_SHA = '906dcd14422450803487475a621fddd9d359ac2e0ea58498772d3c0dbb82d572'
TGG_SHA = 'd8052b44772aacd8cd895d59ccaf89749fe67bfc05a8a8cd55212a3a0e1a13fa'
PARENTS = {
  4250: ('53427cbcd80e315c237d34f4e41bb7ef62ddedd6166d670e6352acb1d45587a1', '9fcd18697938a741771aada9f6a1274b7eada6ae3dc3fb1d7d3771c61f97e537'),
  3200: ('5b3ba3061d9259abfa622beca1c460aad03b0e8af9422c3199b72a58749bc080', '56191940003ee614fe1bd18e0a1a67b946c40db5bf69a08109806eca408ade55'),
}
MAP_X, MAP_Y, P_X, P_Y, D_X, D_Y = 0x13794, 0x13812, 0x13AE2, 0x13B60, 0x139E6, 0x13A64
VERSION_ADDRESSES = tuple(0x4B459 + i * 0x59 for i in range(7))


def require(condition, message):
  if not condition:
    raise ValueError(message)


def sha(data):
  return hashlib.sha256(data).hexdigest()


def words(data, address, count=9):
  return tuple(struct.unpack_from(f'>{count}H', data, address))


def interp(x, xs, ys):
  if x <= xs[0]:
    return float(ys[0])
  for a, b, ya, yb in zip(xs[:-1], xs[1:], ys[:-1], ys[1:], strict=True):
    if x <= b:
      return ya + (yb - ya) * (x - a) / (b - a)
  return float(ys[-1])


def checksums(image):
  first = sum(words(image, START, (0x4FF80 - START) // 2)) & 0xFFFF
  struct.pack_into('>H', image, 0x4FF80, first)
  final = -sum(words(image, START, (0x4FFFE - START) // 2)) & 0xFFFF
  struct.pack_into('>H', image, 0x4FFFE, final)


def build(stock, parent, parent_rwd, tgg, tracker, clarity, response):
  require(sha(stock) == STOCK_SHA and len(stock) == 0x80000, 'unexpected H020 stock image')
  require((sha(parent), sha(parent_rwd)) == PARENTS[tracker], 'unexpected H020 PTM parent pair')
  require(sha(tgg) == TGG_SHA, 'unexpected TGG rev-b reference')
  require(sha(clarity) == CLARITY_SHA, 'unexpected Clarity reference')
  require(response in ('tgg', 'clarity'), 'unknown response target')
  fields, start, payload = parse(parent_rwd)
  require(start == START and payload == parent[START:END], 'parent RWD/bin mismatch')
  require(fields[0] == [b'\0'] and fields[1] == [] and fields[2] == [b'\x30'] and fields[5] == [b'\x01\x02\x03'], 'unexpected header transport fields')
  require([v.rstrip(b'\0') for v in fields[3]] == [b'39990-TEA-H020', OLD_VERSION], 'unexpected parent identities')
  require(len(fields[4]) == 2 and all(key == stock[0x551E4:0x551EA] for key in fields[4]), 'header keys differ from H020 loader')
  require(words(parent, 0x1378E, 1) == (tracker,), 'tracker differs from declared parent')
  require(words(parent, 0x2A70E, 3) == (0, 1650, 0x4680), 'NORM instruction differs')
  require(parent[:START] == stock[:START] and parent[END:] == stock[END:], 'parent changes boot/loader')
  # Addresses are H020's own traced consumers; reference addresses are independently checked TGG's.
  for address in [0x1306C, 0x130A8, 0x130E4, 0x13120]:
    require(parent[address : address + 60] == tgg[address : address + 60], 'TGG/H020 geometry differs')
  require(parent[0x299F0:0x29AB8] == tgg[0x29A50:0x29B18], 'A280 code differs')
  require(parent[0x29AB8:0x29C20] == tgg[0x29B18:0x29C80], 'P/D code differs')
  require(all(parent[0x4B418 + i * 0x59 + 0x0F] == 0 for i in range(5)), 'unexpected selectable row')
  tgg_x, tgg_y = words(tgg, 0x13798), words(tgg, 0x13816)
  require(tgg_x == (0, 103, 263, 459, 660, 862, 1111, 1549, 1774), 'unexpected TGG command axis')
  require(tgg_y == (0, 1740, 4443, 7769, 11167, 14579, 18798, 26202, 30002), 'unexpected TGG command row')
  if response == 'tgg':
    rx, ry, px, py = tgg_x, tgg_y, words(tgg, 0x13AE6), words(tgg, 0x13B64)
  else:
    rx, ry, px, py = words(clarity, 0x13810), words(clarity, 0x1388E), words(clarity, 0x13B5E), words(clarity, 0x13BDC)
  envelope_x, envelope_y = words(clarity, 0x13660), words(clarity, 0x136DE)
  require(envelope_x == (0, 50, 100, 150, 200, 260, 300, 350, 400), 'unexpected Clarity envelope axis')
  require(envelope_y == (1774, 1774, 1774, 1774, 1774, 1330, 1330, 1330, 1330), 'unexpected Clarity envelope values')
  require(words(parent, 0x13890, 3) == words(clarity, 0x1390C, 3) == (7373, 1774, 9000), 'clamp ceilings differ')
  require(words(parent, 0x135BC, 2) == words(clarity, 0x13638, 2) == (0, 400), 'speed clamps differ')
  image = bytearray(parent)
  allowed = set()
  edits = []

  def put(address, values, reason):
    values = tuple(values)
    struct.pack_into(f'>{len(values)}H', image, address, *values)
    allowed.update(range(address, address + 2 * len(values)))
    edits.append({'address': hex(address), 'words': list(values), 'reason': reason})

  for row in range(6):
    xs = words(parent, MAP_X + 18 * row)
    ys = [round(interp(x, rx, ry)) for x in xs]
    # Preserve the reachable last-segment response if its endpoint lies above the 1663 clamp.
    for i, x in enumerate(xs):
      if x > 1663:
        x0, y0 = xs[i - 1], ys[i - 1]
        ys[i] = round(y0 + (interp(1663, rx, ry) - y0) * (x - x0) / (1663 - x0))
    put(MAP_Y + 18 * row, ys, f'row {row}: {response} command response on H020 native axis')
    put(P_X + 18 * row, px, f'row {row}: {response} P knots')
    put(P_Y + 18 * row, py, f'row {row}: {response} P values')
    put(0x135E4 + 18 * row, envelope_x, f'row {row}: Clarity speed envelope axis')
    put(0x13662 + 18 * row, envelope_y, f'row {row}: Clarity speed envelope values')
  for base in [MAP_X, MAP_Y, P_X, P_Y, D_X, D_Y]:
    put(base + 6 * 18, words(stock, base + 6 * 18), 'row 6: restore original H020 stock map/P/D data')
  for address in VERSION_ADDRESSES:
    require(image[address : address + 14] == OLD_VERSION, 'unexpected version literal')
    image[address : address + 14] = NEW_VERSION
    allowed.update(range(address, address + 14))
  checksums(image)
  allowed.update([0x4FF80, 0x4FF81, 0x4FFFE, 0x4FFFF])
  changed = [i for i, (a, b) in enumerate(zip(parent, image, strict=True)) if a != b]
  require(set(changed) <= allowed, 'change outside declared map/P/envelope/row6/identity/checksum writes')
  require(all(START <= i < END for i in changed), 'change outside application')
  require(image[:START] == stock[:START] and image[END:] == stock[END:], 'boot/loader changed')
  require(sum(words(image, START, (END - START) // 2)) & 0xFFFF == 0, 'bad application sum')
  fields[3].append(NEW_VERSION.ljust(16, b'\0'))
  fields[4].append(fields[4][-1])
  rwd = encode(fields, START, bytes(image[START:END]))
  out_fields, out_start, out_payload = parse(rwd)
  require(out_start == START and out_payload == image[START:END] and out_fields == fields, 'new RWD round-trip failed')
  report = {
    'build_id': f'20261022b-{response}-claritylimits-trk{tracker}',
    'eps_version': NEW_VERSION.decode(),
    'tracker': tracker,
    'target_response': response,
    'limits_reference': 'Clarity P-minus-5 A280-flat',
    'source_controller_pin': '92428ab490b3085ea523f79cc6a32d392a057b56',
    'hashes': {
      'stock': sha(stock),
      'parent_image': sha(parent),
      'parent_rwd': sha(parent_rwd),
      'tgg_reference': sha(tgg),
      'clarity_reference': sha(clarity),
      'image': sha(image),
      'payload': sha(image[START:END]),
      'rwd': sha(rwd),
    },
    'flash_region': {'start': hex(START), 'length': hex(END - START)},
    'row0': {
      'r5_key_bp': list(words(image, MAP_X)),
      'r5_v': list(words(image, MAP_Y)),
      'kp_key_bp': list(words(image, P_X)),
      'kp_v': list(words(image, P_Y)),
      'envelope_bp': list(words(image, 0x135E4)),
      'envelope_v': list(words(image, 0x13662)),
    },
    'changed_bytes_vs_parent': len(changed),
    'changed_addresses': [hex(i) for i in changed],
    'word_edits': edits,
    'unchanged': [
      'boot/loader',
      'program code and FF cave',
      'A/B geometry',
      'NORM1650',
      'tracker choice',
      'command X axes rows 0-5',
      'A280 tables',
      'P/D/F clamps',
    ],
    'limits': [
      'offline candidate only',
      'runtime shaping gates and vehicle platform unverified',
      'TGG load/rack/PID are donor values, not H020 road measurements',
      'no timing transfer from TGG',
    ],
  }
  return bytes(image), rwd, report


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument('--inputs', type=Path, required=True)
  parser.add_argument('--output', type=Path, required=True)
  parser.add_argument('--response', choices=['tgg', 'clarity'], required=True)
  args = parser.parse_args()
  require(not args.output.exists(), 'output directory already exists; choose a new one')
  inputs = args.inputs
  built = []
  for tracker in [4250, 3200]:
    image, rwd, report = build(
      (inputs / 'stock.bin').read_bytes(),
      (inputs / f'parent-{tracker}.bin').read_bytes(),
      (inputs / f'parent-{tracker}.rwd').read_bytes(),
      (inputs / 'tgg-revb.bin').read_bytes(),
      tracker,
      (inputs / 'clarity.bin').read_bytes(),
      args.response,
    )
    built.append((tracker, image, rwd, report))
  args.output.mkdir(parents=True)
  for tracker, image, rwd, report in built:
    stem = f'39990-TEA,H02B-20261022b-{args.response.title()}Response-ClarityLimits-Trk{tracker}'
    for suffix, data in [('.full0x80000.bin', image), ('.payload.bin', image[START:END]), ('.rwd', rwd)]:
      (args.output / (stem + suffix)).write_bytes(data)
    (args.output / (stem + '.json')).write_text(json.dumps(report, indent=2) + '\n')
    print(report['build_id'], report['hashes']['rwd'], report['row0']['r5_v'])


if __name__ == '__main__':
  main()
