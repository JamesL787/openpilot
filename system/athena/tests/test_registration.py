import json
import re
from Crypto.PublicKey import RSA
from pathlib import Path

from openpilot.common.params import Params
from openpilot.system.athena.registration import register, IMEI_MAX_ATTEMPTS, UNREGISTERED_DONGLE_ID
from openpilot.system.athena.tests.helpers import MockResponse
from openpilot.system.hardware.hw import Paths


class TestRegistration:

  def setup_method(self):
    # clear params and setup key paths
    self.params = Params()

    persist_dir = Path(Paths.persist_root()) / "comma"
    persist_dir.mkdir(parents=True, exist_ok=True)

    self.priv_key = persist_dir / "id_rsa"
    self.pub_key = persist_dir / "id_rsa.pub"
    self.dongle_id = persist_dir / "dongle_id"

  def _generate_keys(self):
    self.pub_key.touch()
    k = RSA.generate(2048)
    with open(self.priv_key, "wb") as f:
      f.write(k.export_key())
    with open(self.pub_key, "wb") as f:
      f.write(k.publickey().export_key())

  def test_valid_cache(self, mocker):
    # if all params are written, return the cached dongle id.
    # should work with a dongle ID on either /persist/ or normal params
    self._generate_keys()

    dongle = "DONGLE_ID_123"
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    for persist, params in [(True, True), (True, False), (False, True)]:
      self.params.put("DongleId", dongle if params else "")
      with open(self.dongle_id, "w") as f:
        f.write(dongle if persist else "")
      assert register() == dongle
      assert not m.called

  def test_no_keys(self, mocker):
    # missing pubkey
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    dongle = register()
    assert m.call_count == 0
    assert dongle == UNREGISTERED_DONGLE_ID
    assert self.params.get("DongleId") == dongle

  def test_missing_cache(self, mocker):
    # keys exist but no dongle id
    self._generate_keys()
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    dongle = "DONGLE_ID_123"
    m.return_value = MockResponse(json.dumps({'dongle_id': dongle}), 200)
    assert register() == dongle
    assert m.call_count == 1

    # call again, shouldn't hit the API this time
    assert register() == dongle
    assert m.call_count == 1
    assert self.params.get("DongleId") == dongle

  def test_rejected_registration_uses_local_id(self, mocker):
    # keys exist, but unregistered
    self._generate_keys()
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    m.return_value = MockResponse(None, 402)
    dongle = register()
    assert m.call_count == 1
    assert re.fullmatch(r"[a-z0-9]{16}", dongle)
    assert self.params.get("DongleId") == dongle

  def test_imei_wait_is_bounded(self, mocker):
    # no modem: get_imei raises forever, registration must still go ahead with empty IMEIs
    self._generate_keys()
    mocker.patch("openpilot.system.athena.registration.time.sleep")
    get_imei = mocker.patch("openpilot.system.athena.registration.HARDWARE.get_imei", side_effect=Exception("no modem"))
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    m.return_value = MockResponse(json.dumps({'dongle_id': "DONGLE_ID_123"}), 200)
    assert register() == "DONGLE_ID_123"
    assert get_imei.call_count == IMEI_MAX_ATTEMPTS
    assert m.call_args.kwargs["imei"] is None and m.call_args.kwargs["imei2"] is None

  def test_imei_wait_is_bounded_when_registering_konik(self, mocker):
    # the Konik path enters the IMEI loop even when a DongleId already exists
    self._generate_keys()
    self.params.put("DongleId", "DONGLE_ID_123")
    mocker.patch("openpilot.system.athena.registration.time.sleep")
    mocker.patch("openpilot.system.athena.registration.Spinner")
    get_imei = mocker.patch("openpilot.system.athena.registration.HARDWARE.get_imei", side_effect=Exception("no modem"))
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    m.return_value = MockResponse(json.dumps({'dongle_id': "KONIK_ID"}), 200)
    assert register(show_spinner=True, register_konik=True) == "KONIK_ID"
    assert get_imei.call_count == IMEI_MAX_ATTEMPTS

  def test_imei_is_used_when_available(self, mocker):
    self._generate_keys()
    mocker.patch("openpilot.system.athena.registration.HARDWARE.get_imei", side_effect=lambda slot: f"imei{slot}")
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    m.return_value = MockResponse(json.dumps({'dongle_id': "DONGLE_ID_123"}), 200)
    register()
    assert (m.call_args.kwargs["imei"], m.call_args.kwargs["imei2"]) == ("imei0", "imei1")
