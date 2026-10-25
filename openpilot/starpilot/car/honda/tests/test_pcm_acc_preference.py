"""The Clarity PCM-ACC test mode is read from a plain toggle file and attached only to a qualified Clarity."""
import pytest

from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.tests.test_nidec_interceptor import factory
from opendbc.car.honda.values import CAR
from openpilot.starpilot.car.honda.pcm_acc_preference import TOGGLE, attach, enabled


def test_toggle_lives_outside_the_params_directory():
  # manager start archives unregistered files in /data/params/d
  assert "/params/" not in str(TOGGLE)


@pytest.mark.parametrize("contents, expected", [(None, False), (b"0", False), (b"1", True), (b"1\n", True), (b"yes", False)])
def test_toggle_file(tmp_path, contents, expected):
  toggle = tmp_path / "toggle"
  if contents is not None:
    toggle.write_bytes(contents)
  assert enabled(toggle) == expected


@pytest.mark.parametrize("identity, sensor, expected", [(CAR.HONDA_CLARITY, True, True), (CAR.HONDA_CLARITY, False, False),
                                                        (CAR.HONDA_CIVIC, True, False)])
def test_attach_only_on_a_clarity_with_an_interceptor(tmp_path, identity, sensor, expected):
  toggle = tmp_path / "toggle"
  toggle.write_bytes(b"1")
  ci = CarInterface(factory(identity, sensor=sensor))
  assert attach(ci, None, toggle) == expected
  assert ci.CC.keep_pcm_acc == expected and ci.CS.keep_pcm_acc == expected


def test_attach_off_without_the_file(tmp_path):
  ci = CarInterface(factory(CAR.HONDA_CLARITY))
  assert not attach(ci, None, tmp_path / "toggle")
  assert not ci.CC.keep_pcm_acc and not ci.CS.keep_pcm_acc
