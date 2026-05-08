import re
from unittest.mock import patch

from opendbc.car.honda.fingerprints import FW_VERSIONS
from opendbc.car.honda.values import HONDA_BOSCH, HONDA_BOSCH_TJA_CONTROL
from opendbc.car.honda.values import CAR
from opendbc.car import gen_empty_fingerprint
from opendbc.car.car_helpers import interfaces
from opendbc.car.structs import CarParams

HONDA_FW_VERSION_RE = br"[A-Z0-9]{5}(-|,)[A-Z0-9]{3}(-|,)[A-Z0-9]{4}(\x00){2}$"


class TestHondaFingerprint:
  def test_fw_version_format(self):
    # Asserts all FW versions follow an expected format
    for fw_by_ecu in FW_VERSIONS.values():
      for fws in fw_by_ecu.values():
        for fw in fws:
          assert re.match(HONDA_FW_VERSION_RE, fw) is not None, fw

  def test_tja_bosch_only(self):
    assert set(HONDA_BOSCH_TJA_CONTROL).issubset(set(HONDA_BOSCH)), "Nidec car found in TJA control list"


class TestHondaEpsModifiedAnglePid:
  def test_angle_pid_toggle_applies_to_eps_modified_hondas(self):
    car_name = CAR.HONDA_CRV_5G
    fingerprint = gen_empty_fingerprint()
    car_fw = [CarParams.CarFw(ecu="eps", fwVersion=b"39990-TRW,A020\x00\x00")]

    CarInterface = interfaces[car_name]
    CP = CarInterface.get_params(car_name, fingerprint, car_fw, False, False, False)

    with patch("opendbc.car.honda.interface.Params") as MockParams:
      MockParams.return_value.get_bool.return_value = True
      _ = CarInterface.get_params_sp(CP, car_name, fingerprint, car_fw, False, False, False)

    assert CP.lateralTuning.which() == "pid"
