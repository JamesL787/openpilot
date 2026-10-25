"""The Clarity PCM-ACC test mode is read from a raw param file and attached only to a qualified Clarity."""
import pytest

from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.tests.test_nidec_interceptor import factory
from opendbc.car.honda.values import CAR
from openpilot.starpilot.car.honda.pcm_acc_preference import PARAM, attach, enabled


class FileParams:
  def __init__(self, root):
    self.root = root

  def get_param_path(self, key=""):
    return str(self.root / key)


@pytest.mark.parametrize("contents, expected", [(None, False), (b"0", False), (b"1", True), (b"1\n", True), (b"yes", False)])
def test_toggle_file(tmp_path, contents, expected):
  if contents is not None:
    (tmp_path / PARAM).write_bytes(contents)
  assert enabled(FileParams(tmp_path)) == expected


@pytest.mark.parametrize("identity, sensor, expected", [(CAR.HONDA_CLARITY, True, True), (CAR.HONDA_CLARITY, False, False),
                                                        (CAR.HONDA_CIVIC, True, False)])
def test_attach_only_on_a_clarity_with_an_interceptor(tmp_path, identity, sensor, expected):
  (tmp_path / PARAM).write_bytes(b"1")
  ci = CarInterface(factory(identity, sensor=sensor))
  assert attach(ci, FileParams(tmp_path)) == expected
  assert ci.CC.keep_pcm_acc == expected and ci.CS.keep_pcm_acc == expected


def test_attach_off_without_the_file(tmp_path):
  ci = CarInterface(factory(CAR.HONDA_CLARITY))
  assert not attach(ci, FileParams(tmp_path))
  assert not ci.CC.keep_pcm_acc and not ci.CS.keep_pcm_acc
