from unittest.mock import MagicMock

import pytest

from panda import Panda
from panda.python.constants import McuType


def _handle():
  handle = MagicMock()
  handle.controlRead.return_value = b"\x00" * 4 + b"\xde\xad\xd0\x0d" + b"\x00" * 4
  return handle


def _bulk_sizes(mcu_type, size):
  handle = _handle()
  Panda.flash_static(handle, b"\xaa" * size, mcu_type)
  return [len(c.args[1]) for c in handle.bulkWrite.call_args_list]


def test_f4_flashes_in_16_byte_chunks():
  sizes = _bulk_sizes(McuType.F4, 0x100)
  assert set(sizes) == {0x10}
  assert sum(sizes) == 0x100


def test_other_mcus_keep_the_large_chunk():
  sizes = _bulk_sizes(McuType.H7, 0x400)
  assert set(sizes) == {0x200}
  assert sum(sizes) == 0x400


@pytest.mark.parametrize("reply,expected", [
  (b"\x05", Panda.HW_TYPE_DOS),            # clone bootstub
  (b"\x06", Panda.HW_TYPE_DOS),
  (b"\x03", Panda.HW_TYPE_UNO if hasattr(Panda, "HW_TYPE_UNO") else b"\x03"),
  (Panda.HW_TYPE_TRES, Panda.HW_TYPE_TRES),
])
def test_get_type_remaps_only_0x05(reply, expected):
  panda = Panda.__new__(Panda)
  panda._handle = MagicMock()
  panda._handle.controlRead.return_value = reply
  panda._bcd_hw_type = None
  assert panda.get_type() == expected


def test_the_remapped_type_is_an_f4():
  panda = Panda.__new__(Panda)
  panda._handle = MagicMock()
  panda._handle.controlRead.return_value = b"\x05"
  panda._bcd_hw_type = None
  assert panda.get_mcu_type() == McuType.F4
