#!/usr/bin/env python3
"""Minimal SH-2A interpreter for executing THR-A020 ROM functions on synthetic RAM.

Written from the SH-2A ISA encodings. Strict: any opcode not implemented, any
PC-relative load in a delay slot, any write to ROM, and any access outside
ROM / FFF80000-FFF8FFFF raises, so nothing silently goes wrong.
"""

# Adapted from the hash-pinned interpreter in SOURCES.json: ROM injected per CPU;
# no ISA algorithm changes. Formatting only; keep original diagnostic formatting.
# ruff: noqa: UP031

RAM_BASE, RAM_SIZE = 0xFFF80000, 0x10000
STACK_TOP = 0xFFF8FF00
RET_MAGIC = 0x0007FFF0  # erased ROM word; used as sentinel return address

M32 = 0xFFFFFFFF


def s32(x):
  x &= M32
  return x - 0x100000000 if x & 0x80000000 else x


def s16(x):
  x &= 0xFFFF
  return x - 0x10000 if x & 0x8000 else x


def s8(x):
  x &= 0xFF
  return x - 0x100 if x & 0x80 else x


def s12(x):
  x &= 0xFFF
  return x - 0x1000 if x & 0x800 else x


def s20(x):
  x &= 0xFFFFF
  return x - 0x100000 if x & 0x80000 else x


class EmuError(Exception):
  pass


class CPU:
  def __init__(self, rom):
    self.rom = bytes(rom)
    self.ram = bytearray(RAM_SIZE)
    self.R = [0] * 16
    self.T = 0
    self.PR = 0
    self.GBR = 0
    self.SR = 0xF0
    self.MACH = 0
    self.MACL = 0
    self.steps = 0
    self.stubs = {}  # addr -> python fn(cpu) ; emulates call + return
    self.touched_other = set()

  # ---------------- memory ----------------
  def _where(self, a, n, write):
    a &= M32
    if a + n <= len(self.rom) and a < 0x80000:
      if write:
        raise EmuError("write to ROM %08x" % a)
      return self.rom, a
    if RAM_BASE <= a and a + n <= RAM_BASE + RAM_SIZE:
      return self.ram, a - RAM_BASE
    raise EmuError("access outside modeled memory %08x (write=%s)" % (a, write))

  def rd(self, a, n):
    buf, o = self._where(a, n, False)
    return int.from_bytes(buf[o : o + n], "big")

  def wr(self, a, n, v):
    buf, o = self._where(a, n, True)
    buf[o : o + n] = (v & ((1 << (8 * n)) - 1)).to_bytes(n, "big")

  def r8(self, a):
    return s8(self.rd(a, 1)) & M32

  def r16(self, a):
    return s16(self.rd(a, 2)) & M32

  def r32(self, a):
    return self.rd(a, 4)

  # RAM helpers for tests
  def set16(self, a, v):
    self.wr(a, 2, v & 0xFFFF)

  def get16(self, a):
    return s16(self.rd(a, 2))

  def set8(self, a, v):
    self.wr(a, 1, v & 0xFF)

  def set32(self, a, v):
    self.wr(a, 4, v & M32)

  def get32(self, a):
    return s32(self.rd(a, 4))

  # ---------------- execution ----------------
  def call(self, addr, args=(), stack_args=(), max_steps=2_000_000):
    R = self.R
    R[15] = STACK_TOP
    for v in reversed(stack_args):
      R[15] = (R[15] - 4) & M32
      self.wr(R[15], 4, v)
    for i, v in enumerate(args):
      R[4 + i] = v & M32
    self.PR = RET_MAGIC
    self.pc = addr
    self.steps = 0
    while self.pc != RET_MAGIC:
      if self.pc in self.stubs:
        self.stubs[self.pc](self)
        self.pc = self.PR
        continue
      self.step()
      self.steps += 1
      if self.steps > max_steps:
        raise EmuError("step limit")
    return R[0]

  def step(self):
    pc = self.pc
    op = self.rd(pc, 2)
    npc, target, ds = self.exec_op(pc, op, in_delay=False)
    if ds:
      dop = self.rd(pc + 2, 2)
      n2, t2, ds2 = self.exec_op(pc + 2, dop, in_delay=True)
      if ds2 or t2 is not None:
        raise EmuError("branch in delay slot at %x" % (pc + 2))
      if n2 != pc + 2 + (4 if self.is32(dop) else 2):
        pass
      self.pc = target
    else:
      self.pc = target if target is not None else npc

  @staticmethod
  def is32(op):
    t = op >> 12
    lo = op & 0xF
    if t == 0 and lo in (0, 1):
      return True
    if t == 3 and lo in (1, 9):
      return True
    return False

  def exec_op(self, pc, op, in_delay):
    """returns (next_pc, branch_target_or_None, has_delay_slot)"""
    R = self.R
    n = (op >> 8) & 0xF
    m = (op >> 4) & 0xF
    t = op >> 12
    lo = op & 0xF
    d8 = op & 0xFF
    nx = pc + 2

    def pcrel_guard():
      if in_delay:
        raise EmuError("PC-relative in delay slot at %x" % pc)

    # ---- 32-bit forms ----
    if t == 0 and lo in (0, 1):
      w2 = self.rd(pc + 2, 2)
      imm = s20(((op >> 4) & 0xF) << 16 | w2)
      R[n] = (imm << 8 if lo == 1 else imm) & M32
      return pc + 4, None, False
    if t == 3 and lo == 1:
      w2 = self.rd(pc + 2, 2)
      k = w2 >> 12
      d = w2 & 0xFFF
      if k == 0:
        self.wr(R[n] + d, 1, R[m])
      elif k == 1:
        self.wr(R[n] + 2 * d, 2, R[m])
      elif k == 2:
        self.wr(R[n] + 4 * d, 4, R[m])
      elif k == 4:
        R[n] = self.r8(R[m] + d)
      elif k == 5:
        R[n] = self.r16(R[m] + 2 * d)
      elif k == 6:
        R[n] = self.r32(R[m] + 4 * d)
      elif k == 8:
        R[n] = self.rd(R[m] + d, 1)
      elif k == 9:
        R[n] = self.rd(R[m] + 2 * d, 2)
      else:
        raise EmuError("disp12 kind %x at %x" % (k, pc))
      return pc + 4, None, False
    if t == 3 and lo == 9:
      w2 = self.rd(pc + 2, 2)
      k = w2 >> 12
      d = w2 & 0xFFF
      if m & 8:
        raise EmuError("bitop form at %x" % pc)
      bit = m & 7
      a = R[n] + d
      v = self.rd(a, 1)
      if k == 0:
        self.wr(a, 1, v & ~(1 << bit))
      elif k == 1:
        self.wr(a, 1, v | (1 << bit))
      elif k == 2:
        self.wr(a, 1, (v & ~(1 << bit)) | (self.T << bit))
      elif k == 3:
        self.T = (v >> bit) & 1
      elif k == 4:
        self.T &= (v >> bit) & 1
      elif k == 5:
        self.T |= (v >> bit) & 1
      elif k == 6:
        self.T ^= (v >> bit) & 1
      elif k == 0xB:
        self.T = 1 - ((v >> bit) & 1)
      else:
        raise EmuError("bitop kind %x at %x" % (k, pc))
      return pc + 4, None, False

    # ---- 0000 ----
    if t == 0:
      if op == 0x0009:
        return nx, None, False
      if op == 0x0008:
        self.T = 0
        return nx, None, False
      if op == 0x0018:
        self.T = 1
        return nx, None, False
      if op == 0x000B:
        return nx, self.PR, True  # rts
      if op == 0x006B:
        return nx, self.PR, False  # rts/n
      if lo == 0xB and m == 7:
        R[0] = R[n]
        return nx, self.PR, False  # rtv/n
      if lo == 4:
        self.wr(R[0] + R[n], 1, R[m])
        return nx, None, False
      if lo == 5:
        self.wr(R[0] + R[n], 2, R[m])
        return nx, None, False
      if lo == 6:
        self.wr(R[0] + R[n], 4, R[m])
        return nx, None, False
      if lo == 7:
        self.MACL = (s32(R[n]) * s32(R[m])) & M32
        return nx, None, False
      if lo == 0xC:
        R[n] = self.r8(R[0] + R[m])
        return nx, None, False
      if lo == 0xD:
        R[n] = self.r16(R[0] + R[m])
        return nx, None, False
      if lo == 0xE:
        R[n] = self.r32(R[0] + R[m])
        return nx, None, False
      if lo == 9 and m == 2:
        R[n] = self.T
        return nx, None, False  # movt
      if lo == 9 and m == 3:
        R[n] = 1 - self.T
        return nx, None, False  # movrt
      if lo == 2 and m == 1:
        R[n] = self.GBR
        return nx, None, False
      if lo == 2 and m == 0:
        R[n] = (self.SR & ~1) | self.T
        return nx, None, False  # stc sr,rn
      if lo == 0xA and m == 0:
        R[n] = self.MACH
        return nx, None, False
      if lo == 0xA and m == 1:
        R[n] = self.MACL
        return nx, None, False
      if lo == 0xA and m == 2:
        R[n] = self.PR
        return nx, None, False
      if lo == 3 and m == 2:
        return nx, (pc + 4 + R[n]) & M32, True  # braf
      if lo == 3 and m == 0:
        self.PR = pc + 4
        return nx, (pc + 4 + R[n]) & M32, True  # bsrf
    # ---- 0001 ----
    if t == 1:
      self.wr(R[n] + 4 * lo, 4, R[m])
      return nx, None, False
    # ---- 0010 ----
    if t == 2:
      if lo == 0:
        self.wr(R[n], 1, R[m])
      elif lo == 1:
        self.wr(R[n], 2, R[m])
      elif lo == 2:
        self.wr(R[n], 4, R[m])
      elif lo in (4, 5, 6):
        sz = {4: 1, 5: 2, 6: 4}[lo]
        v = R[m]
        R[n] = (R[n] - sz) & M32
        self.wr(R[n], sz, v)
      elif lo == 8:
        self.T = int((R[n] & R[m]) == 0)
      elif lo == 9:
        R[n] &= R[m]
      elif lo == 0xA:
        R[n] ^= R[m]
      elif lo == 0xB:
        R[n] |= R[m]
      elif lo == 0xD:
        R[n] = ((R[m] << 16) | (R[n] >> 16)) & M32
      elif lo == 0xE:
        self.MACL = ((R[n] & 0xFFFF) * (R[m] & 0xFFFF)) & M32
      elif lo == 0xF:
        self.MACL = (s16(R[n]) * s16(R[m])) & M32
      else:
        raise EmuError("op %04x at %x" % (op, pc))
      return nx, None, False
    # ---- 0011 ----
    if t == 3:
      a, b = s32(R[n]), s32(R[m])
      ua, ub = R[n], R[m]
      if lo == 0:
        self.T = int(ua == ub)
      elif lo == 2:
        self.T = int(ua >= ub)
      elif lo == 3:
        self.T = int(a >= b)
      elif lo == 6:
        self.T = int(ua > ub)
      elif lo == 7:
        self.T = int(a > b)
      elif lo == 8:
        R[n] = (ua - ub) & M32
      elif lo == 0xC:
        R[n] = (ua + ub) & M32
      elif lo == 0xE:  # addc
        r = ua + ub + self.T
        R[n] = r & M32
        self.T = r >> 32
      elif lo == 0xA:  # subc
        r = ua - ub - self.T
        R[n] = r & M32
        self.T = int(r < 0)
      elif lo == 0xD:
        p = a * b
        self.MACL = p & M32
        self.MACH = (p >> 32) & M32
      elif lo == 5:
        p = ua * ub
        self.MACL = p & M32
        self.MACH = (p >> 32) & M32
      else:
        raise EmuError("op %04x at %x" % (op, pc))
      return nx, None, False
    # ---- 0100 ----
    if t == 4:
      sub = op & 0xFF
      v = R[n]
      if lo == 0xC:  # shad
        sh = s32(R[m])
        if sh >= 0:
          R[n] = (v << (sh & 31)) & M32
        elif (sh & 31) == 0:
          R[n] = M32 if v & 0x80000000 else 0
        else:
          R[n] = (s32(v) >> ((~sh & 31) + 1)) & M32
        return nx, None, False
      if lo == 0xD:  # shld
        sh = s32(R[m])
        if sh >= 0:
          R[n] = (v << (sh & 31)) & M32
        elif (sh & 31) == 0:
          R[n] = 0
        else:
          R[n] = (v >> ((~sh & 31) + 1)) & M32
        return nx, None, False
      if sub == 0x00:
        self.T = v >> 31
        R[n] = (v << 1) & M32
      elif sub == 0x01:
        self.T = v & 1
        R[n] = v >> 1
      elif sub == 0x20:
        self.T = v >> 31
        R[n] = (v << 1) & M32
      elif sub == 0x21:
        self.T = v & 1
        R[n] = (s32(v) >> 1) & M32
      elif sub == 0x04:
        self.T = v >> 31
        R[n] = ((v << 1) | self.T) & M32
      elif sub == 0x05:
        self.T = v & 1
        R[n] = (v >> 1) | (self.T << 31)
      elif sub == 0x08:
        R[n] = (v << 2) & M32
      elif sub == 0x09:
        R[n] = v >> 2
      elif sub == 0x18:
        R[n] = (v << 8) & M32
      elif sub == 0x19:
        R[n] = v >> 8
      elif sub == 0x28:
        R[n] = (v << 16) & M32
      elif sub == 0x29:
        R[n] = v >> 16
      elif sub == 0x10:
        R[n] = (v - 1) & M32
        self.T = int(R[n] == 0)
      elif sub == 0x11:
        self.T = int(s32(v) >= 0)
      elif sub == 0x15:
        self.T = int(s32(v) > 0)
      elif sub == 0x80:
        R[n] = (s32(R[0]) * s32(v)) & M32  # mulr
      elif sub == 0x94:  # divs r0,rn
        dv = s32(R[0])
        if dv == 0:
          raise EmuError("divs by zero at %x" % pc)
        q = abs(s32(v)) // abs(dv)
        if (s32(v) < 0) != (dv < 0):
          q = -q
        R[n] = q & M32
      elif sub == 0x84:  # divu r0,rn
        if R[0] == 0:
          raise EmuError("divu by zero at %x" % pc)
        R[n] = (v // R[0]) & M32
      elif sub == 0x1E:
        self.GBR = v
      elif sub == 0x0E:
        self.SR = v & 0x3F3
        self.T = v & 1  # ldc rm,sr
      elif sub == 0x2A:
        self.PR = v
      elif sub == 0x1A:
        self.MACL = v
      elif sub == 0x0A:
        self.MACH = v
      elif sub == 0x22:
        R[n] = (v - 4) & M32
        self.wr(R[n], 4, self.PR)
      elif sub == 0x12:
        R[n] = (v - 4) & M32
        self.wr(R[n], 4, self.MACL)
      elif sub == 0x02:
        R[n] = (v - 4) & M32
        self.wr(R[n], 4, self.MACH)
      elif sub == 0x13:
        R[n] = (v - 4) & M32
        self.wr(R[n], 4, self.GBR)
      elif sub == 0x26:
        self.PR = self.r32(v)
        R[n] = (v + 4) & M32
      elif sub == 0x16:
        self.MACL = self.r32(v)
        R[n] = (v + 4) & M32
      elif sub == 0x06:
        self.MACH = self.r32(v)
        R[n] = (v + 4) & M32
      elif sub == 0x17:
        self.GBR = self.r32(v)
        R[n] = (v + 4) & M32
      elif sub == 0x8B:
        self.wr(v, 1, R[0])
        R[n] = (v + 1) & M32
      elif sub == 0x9B:
        self.wr(v, 2, R[0])
        R[n] = (v + 2) & M32
      elif sub == 0xAB:
        self.wr(v, 4, R[0])
        R[n] = (v + 4) & M32
      elif sub == 0x0B:
        self.PR = pc + 4
        return nx, v, True  # jsr
      elif sub == 0x4B:
        self.PR = pc + 2
        return nx, v, False  # jsr/n
      elif sub == 0x2B:
        return nx, v, True  # jmp
      elif sub == 0x91:  # clips.b
        R[n] = max(-128, min(127, s32(v))) & M32
      elif sub == 0x95:
        R[n] = max(-32768, min(32767, s32(v))) & M32
      elif sub == 0x81:
        R[n] = min(v, 0xFF)
      elif sub == 0x85:
        R[n] = min(v, 0xFFFF)
      else:
        raise EmuError("op %04x at %x" % (op, pc))
      return nx, None, False
    # ---- 0101 ----
    if t == 5:
      R[n] = self.r32(R[m] + 4 * lo)
      return nx, None, False
    # ---- 0110 ----
    if t == 6:
      v = R[m]
      if lo == 0:
        R[n] = self.r8(v)
      elif lo == 1:
        R[n] = self.r16(v)
      elif lo == 2:
        R[n] = self.r32(v)
      elif lo == 3:
        R[n] = v
      elif lo in (4, 5, 6):
        sz = {4: 1, 5: 2, 6: 4}[lo]
        val = {1: self.r8, 2: self.r16, 4: self.r32}[sz](v)
        if n != m:
          R[m] = (v + sz) & M32
        R[n] = val
      elif lo == 7:
        R[n] = (~v) & M32
      elif lo == 8:
        R[n] = (v & 0xFFFF0000) | ((v & 0xFF) << 8) | ((v >> 8) & 0xFF)
      elif lo == 9:
        R[n] = ((v << 16) | (v >> 16)) & M32
      elif lo == 0xB:
        R[n] = (-v) & M32
      elif lo == 0xC:
        R[n] = v & 0xFF
      elif lo == 0xD:
        R[n] = v & 0xFFFF
      elif lo == 0xE:
        R[n] = s8(v) & M32
      elif lo == 0xF:
        R[n] = s16(v) & M32
      else:
        raise EmuError("op %04x at %x" % (op, pc))
      return nx, None, False
    # ---- 0111 ----
    if t == 7:
      R[n] = (R[n] + s8(d8)) & M32
      return nx, None, False
    # ---- 1000 ----
    if t == 8:
      sub = n
      if sub == 0:
        self.wr(R[m] + lo, 1, R[0])
      elif sub == 1:
        self.wr(R[m] + 2 * lo, 2, R[0])
      elif sub == 4:
        R[0] = self.r8(R[m] + lo)
      elif sub == 5:
        R[0] = self.r16(R[m] + 2 * lo)
      elif sub == 8:
        self.T = int(R[0] == (s8(d8) & M32))
      elif sub in (9, 0xB, 0xD, 0xF):
        cond = self.T == (1 if sub in (9, 0xD) else 0)
        tgt = (pc + 4 + 2 * s8(d8)) & M32
        if sub in (9, 0xB):
          return nx, (tgt if cond else None), False
        return nx, (tgt if cond else pc + 4), True
      elif sub == 7:  # bld/bst #imm3,Rn  (1000 0111 nnnn xiii)
        rn = (op >> 4) & 0xF
        bit = op & 7
        if op & 8:
          self.T = (R[rn] >> bit) & 1
        else:
          R[rn] = (R[rn] & ~(1 << bit) & M32) | (self.T << bit)
      elif sub == 6:  # bclr/bset #imm3,Rn
        rn = (op >> 4) & 0xF
        bit = op & 7
        if op & 8:
          R[rn] |= 1 << bit
        else:
          R[rn] &= ~(1 << bit) & M32
      else:
        raise EmuError("op %04x at %x" % (op, pc))
      return nx, None, False
    # ---- 1001 / 1101 PC-relative ----
    if t == 9:
      pcrel_guard()
      R[n] = self.r16(pc + 4 + 2 * d8)
      return nx, None, False
    if t == 0xD:
      pcrel_guard()
      R[n] = self.r32((pc & ~3) + 4 + 4 * d8)
      return nx, None, False
    # ---- 1010 / 1011 ----
    if t in (0xA, 0xB):
      d = s12(op & 0xFFF)
      if t == 0xB:
        self.PR = pc + 4
      return nx, (pc + 4 + 2 * d) & M32, True
    # ---- 1100 ----
    if t == 0xC:
      sub = n
      g = self.GBR
      if sub == 0:
        self.wr(g + d8, 1, R[0])
      elif sub == 1:
        self.wr(g + 2 * d8, 2, R[0])
      elif sub == 2:
        self.wr(g + 4 * d8, 4, R[0])
      elif sub == 4:
        R[0] = self.r8(g + d8)
      elif sub == 5:
        R[0] = self.r16(g + 2 * d8)
      elif sub == 6:
        R[0] = self.r32(g + 4 * d8)
      elif sub == 7:
        pcrel_guard()
        R[0] = ((pc & ~3) + 4 + 4 * d8) & M32
      elif sub == 8:
        self.T = int((R[0] & d8) == 0)
      elif sub == 9:
        R[0] &= d8
      elif sub == 0xA:
        R[0] ^= d8
      elif sub == 0xB:
        R[0] |= d8
      else:
        raise EmuError("op %04x at %x" % (op, pc))
      return nx, None, False
    # ---- 1110 ----
    if t == 0xE:
      R[n] = s8(d8) & M32
      return nx, None, False
    raise EmuError("unimplemented op %04x at %x" % (op, pc))
