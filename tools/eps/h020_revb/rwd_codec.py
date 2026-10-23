"""Offline Honda x5A single-block codec; no device or network interface.

Cipher permutation copied as data from rwd-xray tools/eps_tool.py. Header geometry
is parsed strictly; builder preserves the proven H020 header fields and key bytes.
"""

import struct

DECRYPT = bytes.fromhex(
  "24e4a4ead999596483430319ae6e2ec328e8a8eedd9d5d688747071db27232c72cecacf2e1a1616c8b4b0b21b67636cb30f0b0f6e5a565708f4f0f25ba7a3acf34f4b4fae9a9697493531329be7e3ed338f8b8feedad6d789757172dc28242d73cfcbc02f1b1717c9b5b1b31c68646db4000c006f5b575809f5f1f35ca8a4adf4404c40af9b97984a3632339ce8e4ee34808c80efdbd7d88a767273dd29252e74c0ccc1201c1818cab6b2b41d69656eb5010d01605c58590af6f2f45da9a5aef5414d41a09c98994b3733349de9e5ef35818d81e0dcd8d98b777374de2a262f75c1cdc2211d1919cbb7b3b51e6a666fb6020e02615d595a0bf7f3f55aa6a2aff"
)
ENCRYPT = bytes(DECRYPT.index(i) for i in range(256))


def parse(raw):
  if raw[:3] != b"Z\r\n":
    raise ValueError("not Honda x5A RWD")
  if len(raw) < 21:
    raise ValueError("truncated RWD header")
  pos, fields = 3, []
  for _ in range(6):
    if pos >= len(raw):
      raise ValueError("truncated RWD header")
    count = raw[pos]
    pos += 1
    items = []
    for _ in range(count):
      if pos >= len(raw):
        raise ValueError("truncated RWD header")
      size = raw[pos]
      pos += 1
      if pos + size > len(raw):
        raise ValueError("truncated RWD header")
      items.append(raw[pos : pos + size])
      pos += size
    fields.append(items)
  if pos + 8 > len(raw):
    raise ValueError("truncated RWD block")
  start, size = struct.unpack_from(">II", raw, pos)
  pos += 8
  if len(raw) != pos + size + 4:
    raise ValueError("wrong RWD size or multiple blocks")
  if struct.unpack_from("<I", raw, pos + size)[0] != sum(raw[:-4]) & 0xFFFFFFFF:
    raise ValueError("bad RWD file checksum")
  return fields, start, raw[pos : pos + size].translate(DECRYPT)


def encode(fields, start, payload):
  header = bytearray(b"Z\r\n")
  for items in fields:
    header.append(len(items))
    for item in items:
      header.extend(bytes([len(item)]) + item)
  body = bytes(header) + struct.pack(">II", start, len(payload)) + payload.translate(ENCRYPT)
  return body + struct.pack("<I", sum(body) & 0xFFFFFFFF)
