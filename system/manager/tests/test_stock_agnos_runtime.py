"""Runtime pieces comma's stock AGNOS 19.7 does not ship (the MR.ONE clone boots it): bundled pure-Python
packages in starpilot/third_party, and the OpenCV vision processes staying off without cv2."""
import importlib
import json
import os
import sys
from types import SimpleNamespace

import pytest

from openpilot.common.basedir import BASEDIR
import openpilot.system.manager.process_config as pc

THIRD_PARTY = os.path.join(BASEDIR, "starpilot", "third_party")


@pytest.fixture
def bundled(monkeypatch):
  # launch_chffrplus.sh puts starpilot/third_party first on PYTHONPATH
  monkeypatch.syspath_prepend(THIRD_PARTY)
  for name in [m for m in sys.modules if m.split(".")[0] in ("serial", "crcmod", "jsonrpc")]:
    monkeypatch.delitem(sys.modules, name)
  return lambda name: importlib.import_module(name)


@pytest.mark.parametrize("name", ["serial", "crcmod", "jsonrpc"])
def test_package_is_bundled(bundled, name):
  mod = bundled(name)
  assert os.path.dirname(mod.__file__).startswith(THIRD_PARTY)


def test_bundled_crcmod_computes_crcs(bundled):
  crcmod = bundled("crcmod")
  bundled("crcmod.predefined")
  assert crcmod.predefined.mkCrcFun("crc-ccitt-false")(b"123456789") == 0x29B1
  # the form opendbc's Hyundai sender builds, against a bit-by-bit CRC-8 (poly 0x1D, xorout 0xDF);
  # crcmod's initCrc is the starting register XORed with xorOut, so the register starts at 0xFD ^ 0xDF
  def crc8(data, crc=0xFD ^ 0xDF):
    for byte in data:
      crc ^= byte
      for _ in range(8):
        crc = ((crc << 1) ^ 0x1D) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc ^ 0xDF
  hyundai = crcmod.mkCrcFun(0x11D, initCrc=0xFD, rev=False, xorOut=0xDF)
  for data in (b"\x00", b"\x12\x34\x56\x78", bytes(range(7))):
    assert hyundai(data) == crc8(data)


def test_bundled_pyserial_has_posix_serial(bundled):
  serial = bundled("serial")
  assert hasattr(serial, "Serial") and hasattr(serial, "SerialException")


def test_bundled_jsonrpc_answers_a_request(bundled):
  jsonrpc = bundled("jsonrpc")
  dispatcher = {"echo": lambda x: x}
  response = jsonrpc.JSONRPCResponseManager.handle(json.dumps({"jsonrpc": "2.0", "method": "echo", "params": [7], "id": 1}), dispatcher)
  assert response.data["result"] == 7


@pytest.mark.parametrize("opencv", [True, False])
def test_vision_processes_need_opencv(monkeypatch, opencv):
  monkeypatch.setattr(pc, "OPENCV_AVAILABLE", opencv)
  toggles = SimpleNamespace(vision_speed_limit_detection=True, v_asm_enabled=True)
  assert pc.run_speed_limit_vision(True, None, None, toggles) is opencv
  assert pc.run_v_asm(True, None, None, toggles) is opencv
