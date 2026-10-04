#!/usr/bin/env python3
"""Static check of HONDA-BOSCH-ACC-BRAKE-INTERNALS-01 (the ACC brake-pipeline PDF, Oct 2026) against itself.

The firmware image (36802TBA.dec.bin) and its disassembly are NOT in this repo, so nothing here proves the PDF
matches the firmware. What this does check, with no external files:

  1. every instruction the PDF prints as `address  hexword  mnemonic` is re-decoded from the hex word (PowerPC VLE
     / Book E), and its operands, branch targets and the listing's address continuity are compared with the text;
  2. the PDF's arithmetic (unit identities, SDA addresses, reciprocal divide, float table, CAN scaling);
  3. its CAN tables against the opendbc DBC this repo actually packs with.

Run: python tools/fw_acc_brake_pdf_check.py   (exit status 1 if any check disagrees with the PDF's text)

Result 2026-10-04 on the PDF with sha256 1f59c26eae913c17d219ab5b31d4960e57e8917205b1aa5249532254c18a1333 (the
PDF itself is not committed): 167 checks agree, 6 disagree -- all [CONFIRMED static, PDF self-consistency only]:
  * 0x72d4e 5c6dffe8 is e_sth r3,-0x18(r13), not -0x16(r29), and the /5 quotient is in r12: the v_ref store claim
    is not supported by its own hex.
  * 0xdf450 1c60e938 has rA=0 (r3 = -0x16c8), so it cannot form r3 = 0x15e938; 0xdf454 e_bl goes to 0xbb20c, not
    0x11f608. The 0x1DF packer listing (8.1) is unreliable as printed.
  * 0xd0c58 is 90 bytes, not 88 (the min(a,b) law itself decodes exactly as the PDF states).
  * 0x1DF table: COUNTER is 61|2 and CHECKSUM 59|4 in the DBC; the PDF's 59/4 and 55/4 are wrong.
Notes, not counted: 0x14366c branch sense is the reverse of the PDF's comment; the iselgt "max" claims at
0xd0bba/0xd0bd8 lack the printed compare; IIR alphas give 8 s / 1.6 s time constants; the 6.4 "-10 counts" is CAN
0.01 units (-205 in Q11); the 0x1DF table omits five DBC signals.
Bearing on radar_interface.py: none contradicted. The PDF's Q7 (1/128 m) distance unit matches the parser's
firmware form range = (8*raw - n)/128. The PDF does not cover the 0x280-0x297 track decode, U11, azimuth or offset.
"""
import ctypes
import struct
import sys
from pathlib import Path

FAILS: list[str] = []
NOTES: list[str] = []


def check(ok: bool, what: str) -> None:
  print(("OK    " if ok else "DIFF  ") + what)
  if not ok:
    FAILS.append(what)


def s16(x: int) -> int:
  return x - 0x10000 if x & 0x8000 else x


# ---- minimal VLE decoder: only the forms the PDF prints -------------------------------------------------------------

def gpr4(r: int) -> int:  # se_* 4-bit register field: 0-7 -> r0-r7, 8-15 -> r24-r31
  return r if r < 8 else r + 16


def decode(pc: int, hexword: str):
  """Return (mnemonic, operands tuple, size)."""
  w = int(hexword, 16)
  if len(hexword) == 4:
    if w == 0x0004:
      return "se_blr", (), 2
    if w == 0x0007:
      return "se_bctrl", (), 2
    if w & 0xFFF0 == 0x00B0:
      return "se_mtctr", (w & 15,), 2
    if w & 0xFFF0 == 0x00F0:
      return "se_extsh", (gpr4(w & 15),), 2
    if w & 0xFF00 == 0x0100:
      return "se_mr", (gpr4(w & 15), gpr4((w >> 4) & 15)), 2
    if w & 0xFF00 == 0x0C00:
      return "se_cmp", (gpr4(w & 15), gpr4((w >> 4) & 15)), 2
    if w & 0xFE00 == 0x2C00:
      return "se_bmaski", (gpr4(w & 15), (w >> 4) & 31), 2
    if w & 0xF800 == 0x4800:
      return "se_li", (gpr4(w & 15), (w >> 4) & 0x7F), 2
    if w & 0xFE00 == 0x6A00:
      return "se_srawi", (gpr4(w & 15), (w >> 4) & 31), 2
    if w >> 12 in (0x8, 0x9, 0xB):  # se_lbz / se_stb / se_sth  rZ, SD4(rX)
      name, scale = {0x8: ("se_lbz", 1), 0x9: ("se_stb", 1), 0xB: ("se_sth", 2)}[w >> 12]
      return name, (gpr4((w >> 4) & 15), ((w >> 8) & 15) * scale, gpr4(w & 15)), 2
    if w & 0xFC00 == 0xE800:  # se_b / se_bl
      bd = w & 0xFF
      bd = bd - 256 if bd & 0x80 else bd
      return ("se_bl" if w & 0x100 else "se_b"), (pc + 2 * bd,), 2
    if w & 0xF800 == 0xE000:  # se_bc
      bd = w & 0xFF
      bd = bd - 256 if bd & 0x80 else bd
      bo, bi = (w >> 10) & 1, (w >> 8) & 3
      cond = ["lt", "gt", "eq", "so"][bi] if bo else ["ge", "le", "ne", "ns"][bi]
      return "se_b" + cond, (pc + 2 * bd,), 2
    return "?16", (), 2
  op = w >> 26
  rd, ra = (w >> 21) & 31, (w >> 16) & 31
  d16 = s16(w & 0xFFFF)
  dforms = {12: "e_lbz", 13: "e_stb", 14: "e_lha", 20: "e_lwz", 22: "e_lhz", 23: "e_sth", 7: "e_add16i"}
  if op in dforms:
    if op == 7:
      return "e_add16i", (rd, ra, d16), 4
    return dforms[op], (rd, d16, ra), 4
  if op == 30:  # e_b / e_bl, BD24
    disp = w & 0x01FFFFFE
    if disp & 0x01000000:
      disp -= 0x02000000
    return ("e_bl" if w & 1 else "e_b"), (pc + disp,), 4
  if op == 28:
    xo = (w >> 11) & 31
    if (w >> 15) & 1 == 0:  # e_li, LI20
      li = (((w >> 11) & 15) << 16) | (((w >> 16) & 31) << 11) | (w & 0x7FF)
      return "e_li", (rd, li - (1 << 20) if li & 0x80000 else li), 4
    if xo == 0x1C:  # e_lis
      return "e_lis", (rd, (((w >> 16) & 31) << 11) | (w & 0x7FF)), 4
    if xo == 0x13:  # e_cmp16i, I16A
      si = (rd << 11) | (w & 0x7FF)
      return "e_cmp16i", (ra, s16(si)), 4
  if op == 29:
    return "e_rlwinm", (ra, rd, (w >> 11) & 31, (w >> 6) & 31, (w >> 1) & 31), 4
  if op == 6:  # SCI8 class: e_addi / e_andi / e_ori / e_cmpi / e_stwu -- operands only, immediate not expanded
    return "sci8", (rd, ra, (w >> 12) & 15, w & 0xFF), 4
  if op == 4 and (w & 0x7FF) == 0x2D1:
    return "efscfsi", (rd, (w >> 11) & 31), 4
  if op == 31:
    rb, xo10 = (w >> 11) & 31, (w >> 1) & 0x3FF
    if xo10 & 0x1F == 15:
      return "isel" + ["lt", "gt", "eq", "so"][(w >> 6) & 3], (rd, ra, rb, (w >> 8) & 7), 4
    table = {0: "cmpw", 75: "mulhw", 266: "add", 40: "subf", 104: "neg", 824: "srawi", 922: "extsh"}
    name = table.get(xo10, "?31")
    if name == "cmpw":
      return name, ((w >> 23) & 7, ra, rb), 4
    if name in ("srawi",):
      return name, (ra, rd, rb), 4
    if name == "extsh":
      return name, (ra, rd), 4
    return name, (rd, ra, rb), 4
  return "?32", (), 4


# Each listing: (section, [(pc, hex, mnemonic, operands-as-the-PDF-prints-them)]).  Operands: registers as ints,
# displacements/immediates as signed ints, branch targets as absolute addresses.  None = not checked.
LISTINGS = [
  ("2.3 COM 0x276 ingest", [
    (0x143630, "516d8c78", "e_lwz", (11, -0x7388, 13)),
    (0x143634, None, None, None),  # gap in the PDF listing (0x143634..0x143641 not printed)
    (0x143642, "70600276", "e_li", (3, 0x276)),
    (0x143646, None, None, None),  # gap in the PDF listing (0x143646..0x143653 not printed)
    (0x143654, "78007071", "e_bl", (0x14A6C4,)),
    (0x143658, "70600274", "e_li", (3, 0x274)),
    (0x14365C, "18818009", "sci8", None),
    (0x143660, "78007065", "e_bl", (0x14A6C4,)),
    (0x143664, "31610009", "e_lbz", (11, 9, 1)),
    (0x143668, "180ba801", "sci8", None),
    (0x14366C, "e203", "se_bne", (0x143672,)),
    (0x14366E, "1bbdc600", "sci8", None),
  ]),
  ("3.2 v_ref /5", [
    (0x72D38, "710ce666", "e_lis", (8, 0x6666)),
    (0x72D3C, "1d086667", "e_add16i", (8, 8, 0x6667)),
    (0x72D40, "7d880096", "mulhw", (12, 8, 0)),
    (0x72D44, "6bf0", "se_srawi", (0, 0x1F)),
    (0x72D46, "7d8c0e70", "srawi", (12, 12, 1)),
    (0x72D4A, "7d806050", "subf", (12, 0, 12)),
    (0x72D4E, "5c6dffe8", "e_sth", (3, -0x16, 29)),
  ]),
  ("3.4 IIR commit", [
    (0x72EA0, "587dfff2", "e_lhz", (3, -0xE, 29)),
    (0x72EA4, "5c7dfff6", "e_sth", (3, -0xA, 29)),
  ]),
  ("3.5 trim", [
    (0x730E4, "516d8378", "e_lwz", (11, -0x7C88, 13)),
    (0x730E8, "387dfff6", "e_lha", (3, -0xA, 29)),
    (0x730EC, "388b0002", "e_lha", (4, 2, 11)),
    (0x730F0, "4925", "se_li", (5, 0x12)),
    (0x730F2, "7802910f", "e_bl", (0x9C200,)),
    (0x730F6, "0134", "se_mr", (4, 3)),
    (0x730F8, "387dfff6", "e_lha", (3, -0xA, 29)),
    (0x730FC, "780290a7", "e_bl", (0x9C1A2,)),
    (0x73100, "518d8390", "e_lwz", (12, -0x7C70, 13)),
    (0x73104, "5c6c0018", "e_sth", (3, 0x18, 12)),
  ]),
  ("4.2 negation ingest", [
    (0xBC5C6, "50cd8994", "e_lwz", (6, -0x766C, 13)),
    (0xBC5CA, "58e60194", "e_lhz", (7, 0x194, 6)),
    (0xBC5CE, None, None, None),
    (0xBC5D2, "58e60196", "e_lhz", (7, 0x196, 6)),
    (0xBC5D6, None, None, None),
    (0xBC5DA, "5061009c", "e_lwz", (3, 0x9C, 1)),
    (0xBC5DE, "7c68c471", None, None),  # e_srwi. (rlwinm. form) -- not decoded here
    (0xBC5E2, "e610", "se_beq", (0xBC602,)),
    (0xBC5E4, "7469863f", "e_rlwinm", (9, 3, 0x10, 0x18, 0x1F)),
    (0xBC5E8, "1809a801", "sci8", None),
    (0xBC5EC, None, None, None),
    (0xBC5EE, "e213", "se_bne", (0xBC614,)),
    (0xBC5F0, "00f3", "se_extsh", (3,)),
    (0xBC5F2, "79fdfd17", "e_bl", (0x9C308,)),
    (0xBC5F6, "514d89a0", "e_lwz", (10, -0x7660, 13)),
    (0xBC5FA, "4835", "se_li", (5, 3)),
    (0xBC5FC, "5c6a0012", "e_sth", (3, 0x12, 10)),
    (0xBC600, None, None, None),
    (0xBC614, "50cd89a0", "e_lwz", (6, -0x7660, 13)),
    (0xBC618, "34a60033", "e_stb", (5, 0x33, 6)),
  ]),
  ("4.2 neg_sat16 0x9c308", [
    (0x9C308, "0130", "se_mr", (0, 3)),
    (0x9C30A, "72039800", "e_cmp16i", (3, -0x8000)),
    (0x9C30E, "2cf3", "se_bmaski", (3, 0xF)),
    (0x9C310, "e604", "se_beq", (0x9C318,)),
    (0x9C312, "7c6000d0", "neg", (3, 0, 0)),
    (0x9C316, "00f3", "se_extsh", (3,)),
    (0x9C318, "0004", "se_blr", ()),
  ]),
  ("4.3 gate + FIR", [
    (0x7095A, "182106d0", "sci8", None),
    (0x7095E, None, None, None),
    (0x70966, "50ed8368", "e_lwz", (7, -0x7C98, 13)),
    (0x7096A, "50ad838c", "e_lwz", (5, -0x7C74, 13)),
    (0x7096E, "31070033", "e_lbz", (8, 0x33, 7)),
    (0x70972, "1909c801", "sci8", None),
    (0x70976, "8405", "se_lbz", (0, 4, 5)),
    (0x70978, "e60b", "se_beq", (0x7098E,)),
    (0x7097A, "180ad0c0", "sci8", None),
    (0x7097E, "35450004", "e_stb", (10, 4, 5)),
    (0x70982, "518d8368", "e_lwz", (12, -0x7C98, 13)),
    (0x70986, "386c0012", "e_lha", (3, 0x12, 12)),
    (0x7098A, "e9c0", "se_bl", (0x7090A,)),
    (0x7098C, "e806", "se_b", (0x70998,)),
    (0x7098E, "1800c43f", "sci8", None),
    (0x70992, "4803", "se_li", (3, 0)),
    (0x70994, "9405", "se_stb", (0, 4, 5)),
    (0x70996, "e9ba", "se_bl", (0x7090A,)),
    (0x70998, "510d838c", "e_lwz", (8, -0x7C74, 13)),
    (0x7099C, "5c680000", "e_sth", (3, 0, 8)),
  ]),
  ("4.3 FIR /5", [
    (0x70936, "710ce666", "e_lis", (8, 0x6666)),
    (0x7093A, "1d086667", "e_add16i", (8, 8, 0x6667)),
    (0x7093E, "7c005214", "add", (0, 0, 10)),
    (0x70942, "7d880096", "mulhw", (12, 8, 0)),
    (0x70946, "6bf0", "se_srawi", (0, 0x1F)),
    (0x70948, "7d8c0e70", "srawi", (12, 12, 1)),
    (0x7094C, "7d806050", "subf", (12, 0, 12)),
    (0x70950, "5c6dac50", "e_sth", (3, -0x53B0, 13)),
    (0x70954, "7d830734", "extsh", (3, 12)),
  ]),
  ("5.1 caller 0xdb56c", [
    (0xDB576, "51830004", "e_lwz", (12, 4, 3)),
    (0xDB57A, "500c007c", "e_lwz", (0, 0x7C, 12)),
    (0xDB57E, "00b0", "se_mtctr", (0,)),
    (0xDB580, "013f", "se_mr", (31, 3)),
    (0xDB582, "0007", "se_bctrl", ()),
    (0xDB584, "5c7f0070", "e_sth", (3, 0x70, 31)),
  ]),
  ("5.2 0xd0c58 arbitration", [
    (0xD0C58, "514d8a78", "e_lwz", (10, -0x7588, 13)),
    (0xD0C5C, "512d8a68", "e_lwz", (9, -0x7598, 13)),
    (0xD0C60, "518d8adc", "e_lwz", (12, -0x7524, 13)),
    (0xD0C64, "394a0018", "e_lha", (10, 0x18, 10)),
    (0xD0C68, "38090000", "e_lha", (0, 0, 9)),
    (0xD0C6C, "316c0000", "e_lbz", (11, 0, 12)),
    (0xD0C70, "312c0003", "e_lbz", (9, 3, 12)),
    (0xD0C74, "7c0a0000", "cmpw", (0, 10, 0)),
    (0xD0C78, "7c6a001e", "isellt", (3, 10, 0, 0)),
    (0xD0C7C, "180ba801", "sci8", None),
    (0xD0C80, "00f3", "se_extsh", (3,)),
    (0xD0C82, "e604", "se_beq", (0xD0C8A,)),
    (0xD0C84, "180ba802", "sci8", None),
    (0xD0C88, "e208", "se_bne", (0xD0C98,)),
    (0xD0C8A, "394c001c", "e_lha", (10, 0x1C, 12)),
    (0xD0C8E, "7c0a1800", "cmpw", (0, 10, 3)),
    (0xD0C92, "7c6a181e", "isellt", (3, 10, 3, 0)),
    (0xD0C96, "0004", "se_blr", ()),
    (0xD0C98, "1809a801", "sci8", None),
    (0xD0C9C, "e604", "se_beq", (0xD0CA4,)),
    (0xD0C9E, "1809a802", "sci8", None),
    (0xD0CA2, "e207", "se_bne", (0xD0CB0,)),
    (0xD0CA4, "394c0018", "e_lha", (10, 0x18, 12)),
    (0xD0CA8, "7c0a1800", "cmpw", (0, 10, 3)),
    (0xD0CAC, "7c6a181e", "isellt", (3, 10, 3, 0)),
    (0xD0CB0, "0004", "se_blr", ()),
  ]),
  ("6.1 relay 0xd0b6c", [
    (0xD0BA6, "38de0072", "e_lha", (6, 0x72, 30)),
    (0xD0BAA, "380c3b4a", "e_lha", (0, 0x3B4A, 12)),
    (0xD0BAE, None, None, None),
    (0xD0BBA, "7c06005e", "iselgt", (0, 6, 0, 0)),
    (0xD0BBE, None, None, None),
    (0xD0BB6, "393e0070", "e_lha", (9, 0x70, 30)),
    (0xD0BBA, None, None, None),
    (0xD0BD8, "7d09005e", "iselgt", (8, 9, 0, 0)),
    (0xD0BDC, None, None, None),
    (0xD0C0C, "512d8b50", "e_lwz", (9, -0x74B0, 13)),
    (0xD0C10, "5c090004", "e_sth", (0, 4, 9)),
    (0xD0C14, "516d8b50", "e_lwz", (11, -0x74B0, 13)),
    (0xD0C18, "5d0b0006", "e_sth", (8, 6, 11)),
  ]),
  ("6.2/6.3 rate limiter", [
    (0x7C7D2, "510d8440", "e_lwz", (8, -0x7BC0, 13)),
    (0x7C7D6, None, None, None),
    (0x7C7DE, "3b880006", "e_lha", (28, 6, 8)),
    (0x7C7E2, "3aa80004", "e_lha", (21, 4, 8)),
    (0x7C7E6, None, None, None),
    (0x7C81C, "7c14a800", "cmpw", (0, 20, 21)),
    (0x7C820, "7fb4a85e", "iselgt", (29, 20, 21, 0)),
    (0x7C824, "0c0d", "se_cmp", (29, 0)),
    (0x7C826, "7fbd005e", "iselgt", (29, 29, 0, 0)),
    (0x7C82A, None, None, None),
    (0x79C60, "0ce3", "se_cmp", (3, 30)),
    (0x79C62, "7c63f01e", "isellt", (3, 3, 30, 0)),
  ]),
  ("7.1/7.2 mode arbiter", [
    (0xEF508, "59280002", "e_lhz", (9, 2, 8)),
    (0xEF50C, None, None, None),
    (0xEF524, "5d3efff4", "e_sth", (9, -0xC, 30)),
    (0xEF528, None, None, None),
    (0xEAB9A, "50cd8df0", "e_lwz", (6, -0x7210, 13)),
    (0xEAB9E, "b6f6", "se_sth", (31, 0xC, 6)),
  ]),
  ("8.1 packer 0xdf444", [
    (0xDF440, "50ed8c74", "e_lwz", (7, -0x738C, 13)),
    (0xDF444, "3807000c", "e_lha", (0, 0xC, 7)),
    (0xDF448, None, None, None),  # PDF jumps 0xdf444 -> 0xdf44c: 4 bytes not printed
    (0xDF44C, "108002d1", "efscfsi", (4, 0)),
    (0xDF450, "1c60e938", "e_add16i", (3, 3, -0x16C8)),  # PDF: "r3 = 0x15e938" needs r3 = 0x160000 + (-0x16c8)
    (0xDF454, "79fdbdb9", "e_bl", (0x11F608,)),
  ]),
]


def run_listings() -> None:
  print("== 1. instruction encodings vs the PDF's mnemonics ==")
  for section, rows in LISTINGS:
    nxt = None
    for pc, hexword, mnem, ops in rows:
      if hexword is None:
        nxt = None  # the PDF skips bytes here; restart the continuity check
        continue
      name, got, size = decode(pc, hexword)
      if nxt is not None and pc != nxt:
        check(False, f"[{section}] {pc:#x}: listing continuity, previous instruction ends at {nxt:#x}")
      nxt = pc + size
      if mnem is None:
        continue
      if name != mnem:
        check(False, f"[{section}] {pc:#x} {hexword}: decodes as {name} {got}, PDF prints {mnem}")
        continue
      if ops is None:
        continue
      label = ", ".join(hex(o) if abs(o) > 9 else str(o) for o in got)
      check(got == ops, f"[{section}] {pc:#x} {hexword}: {name} {label}" +
            ("" if got == ops else f"  (PDF prints {', '.join(hex(o) for o in ops)})"))
  NOTES.append("0x14366c se_bne -> 0x143672 jumps OVER the e_andi at 0x14366e when the compared byte != 1, so the " +
               "clear runs when it == 1 (valid); the PDF's comments describe the opposite sense")
  NOTES.append("0xd0bba / 0xd0bd8 iselgt: the compare that sets cr0 is not printed, so 'max(...)' there is unproven")
  # 0xd0c58 length: the PDF says 88 bytes
  check(0xD0CB2 - 0xD0C58 == 88, f"0xd0c58 length: last se_blr ends at 0xd0cb2 -> {0xD0CB2 - 0xD0C58} bytes (PDF: 88)")


def run_arithmetic() -> None:
  print("\n== 2. arithmetic ==")
  check((1 / 256) ** 2 == 4 * (1 / 128) * (1 / 2048), "Sv^2 = 4 Sd Sa with Sv=1/256, Sd=1/128, Sa=1/2048")
  check(round(36.00 / 3.6 * 256) == 2560, "36.00 km/h -> 2560 Q8 counts")
  check(2048 * 2048 // 256 == 16384 == 1 << 14, "dv(Q8)/dt(41/2048 s) in Q11 = dY*16384/41 = (dY<<14)/41")
  check(abs(41 / 2048 - 0.0200195) < 1e-7, "dt = 41/2048 s = 20.02 ms")
  for name, alpha in (("stage 1", 0xA4), ("stage 2", 0x333)):
    k = alpha / 65536
    tau = (41 / 2048) / k
    dead = 65536 / alpha
    NOTES.append(f"IIR {name}: alpha {alpha}/2^16 = {k:.5f}/step -> time constant {tau:.2f} s at 20 ms; with " +
                 f"truncation, |x-y| < {dead:.0f} Q11 counts ({dead / 2048:.3f} m/s^2) moves the state by 0")
  check(abs(100 / 262144 - 0.000381) < 1e-6, "K: 1 count = 2^-18 = 0.000381 %")
  table = struct.unpack(">4f", struct.pack(">4f", 0.0478515625, -24.5, 2048.0, 1.0))
  check(table == (0.0478515625, -24.5, 2048.0, 1.0), "float table values are exact in f32")
  check(all(((r * table[0] + table[1]) * table[3]) * table[2] == r * 98 - 50176 for r in range(4096)),
        "((raw*0.0478515625 - 24.5)*1.0)*2048 == raw*98 - 50176 for raw 0..4095")

  def div5_asm(n: int) -> int:
    hi = (0x66666667 * n) >> 32
    return (hi >> 1) - (-1 if n < 0 else 0)
  check(0x66666667 == (1 << 33) // 5 + 1, "M = 0x66666667 = floor(2^33/5) + 1")
  check(all(div5_asm(x) == int(x / 5) for x in range(-5 * 32768, 5 * 32768)), "div5 == trunc(S/5) for all 5*int16 sums")

  def neg_sat16(x: int) -> int:
    return 0x7FFF if x == -0x8000 else ctypes.c_int16(-x).value
  check(neg_sat16(-32768) == 32767 and all(neg_sat16(x) == -x for x in range(-32767, 32768)), "neg_sat16")
  for phys, counts in ((-2.5, -5120), (0.5, 1024), (-2.0, -4096), (-3.5, -7168), (-1.0, -2048), (-4.0, -8192),
                       (2.0, 4096), (-9.0, -18432), (-6.0, -12288), (-1.25, -2560)):
    check(round(phys * 2048) == counts, f"{phys:+} m/s^2 = {counts} Q11")
  check(-2560 * 41 // 512 == -205 and abs(-205 / 2048 / (41 / 2048) + 5.0) < 0.01, "dn = -205 counts/call ~ -5.0 m/s^3")
  check(-205 != -10, "6.4 says the slew limit is '-10 counts/frame (-0.10 m/s^2)': -0.10 m/s^2 is -205 Q11 counts; " +
        "-10 is in CAN 0.01 m/s^2 units")
  check(round(1.01 - (-1.13), 2) == 2.14, "+1.01 -> -1.13 m/s^2 is a 2.14 m/s^2 drop")
  check(0x7332C - 0x725D2 == 3418 and 0x7332C - 0x73128 == 516, "0x725d2..0x7332c = 3418 B; 516 B after 0x73128")
  r13 = 0x4001A458 + 0x5298
  check(r13 == 0x4001F6F0, "r13 = 0x4001F6F0 (from r29 = r13 - 0x5298 = 0x4001A458)")
  for what, got, want in (("struct A", 0x40040000 - 0x4EBC, 0x4003B144), ("struct B", r13 - 0x4D00, 0x4001A9F0),
                          ("buffer G", r13 - 0x4AA0, 0x4001AC50), ("P+2", r13 - 0x4A00 + 2, 0x4001ACF2),
                          ("FIR delay", r13 - 0x53B0, 0x4001A340), ("vtable", 0x160000 - 0x27F8, 0x15D808),
                          ("vtable[0x7c]", 0x15D808 + 0x7C, 0x15D884), ("file offset", 0x16661C - 0x30000, 0x13661C)):
    check(got == want, f"{what}: {got:#x}")


DBC = Path(__file__).resolve().parents[1] / "opendbc_repo/opendbc/dbc/generator/honda/_bosch_radar_acc.dbc"
PT_DBC = Path(__file__).resolve().parents[1] / "opendbc_repo/opendbc/dbc/honda_civic_hatchback_ex_2017_can_generated.dbc"


def motorola_lsb(msb: int, length: int) -> int:
  bit = msb
  for _ in range(length - 1):
    bit = bit + 15 if bit % 8 == 0 else bit - 1
  return bit


def dbc_signals(path: Path, msg: str) -> dict:
  out, inside = {}, False
  for line in path.read_text().splitlines():
    if line.startswith("BO_ "):
      inside = line.split()[2].rstrip(":") == msg
    elif inside and line.strip().startswith("SG_"):
      p = line.split()
      start, length = p[3].split("|")
      out[p[1]] = (int(start), int(length.split("@")[0]), p[4])
  return out


def run_dbc() -> None:
  print("\n== 3. CAN tables vs the opendbc DBC this repo packs with ==")
  ws = dbc_signals(PT_DBC, "WHEEL_SPEEDS")
  for sig, pdf_start in (("FL", 9), ("FR", 26), ("RL", 43), ("RR", 60)):
    msb, length, _ = ws["WHEEL_SPEED_" + sig]
    check(length == 15 and motorola_lsb(msb, length) == pdf_start,
          f"0x1D0 {sig}: DBC {msb}|{length} -> LSB {motorola_lsb(msb, length)} (PDF 'start' {pdf_start}, LSB convention)")
  acc = dbc_signals(DBC, "ACC_CONTROL")
  pdf = {"ACCEL_COMMAND": (31, 11), "BRAKE_REQUEST": (34, 1), "GAS_COMMAND": (8, 16), "STANDSTILL": (35, 1),
         "AEB_PREPARE": (43, 1), "BRAKE_LIGHTS": (62, 1), "COUNTER": (59, 4), "CHECKSUM": (55, 4)}
  for sig, (start, length) in pdf.items():
    msb, dlen, _ = acc[sig]
    lsb = motorola_lsb(msb, dlen)
    check(dlen == length and start in (msb, lsb),
          f"0x1DF {sig}: DBC {msb}|{dlen} (LSB {lsb}); PDF start {start} len {length}")
  missing = sorted(set(acc) - set(pdf))
  NOTES.append(f"0x1DF signals in the DBC that the PDF table omits: {', '.join(missing)}")
  check(acc["ACCEL_COMMAND"][2].startswith("(0.01,0)"), "ACCEL_COMMAND scale 0.01 m/s^2 in the DBC")


if __name__ == "__main__":
  run_listings()
  run_arithmetic()
  run_dbc()
  print("\nNOTES")
  for n in NOTES:
    print("  " + n)
  print(f"\n{len(FAILS)} disagreement(s) with the PDF's text")
  sys.exit(1 if FAILS else 0)
