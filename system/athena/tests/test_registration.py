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

  def _fake_clock(self, mocker):
    now = [0.]

    def sleep(s):
      now[0] += s
    mocker.patch("openpilot.system.athena.registration.time.sleep", side_effect=sleep)
    mocker.patch("openpilot.system.athena.registration.time.monotonic", side_effect=lambda: now[0])
    return now

  def test_konik_registration_gives_up(self, mocker):
    # unreachable server: no endless retry, spinner closed, nothing written, caller sees None
    self._generate_keys()
    self.params.put("DongleId", "DONGLE_ID_123")
    now = self._fake_clock(mocker)
    spinner = mocker.patch("openpilot.system.athena.registration.Spinner")
    mocker.patch("openpilot.system.athena.registration.HARDWARE.get_imei", side_effect=lambda slot: f"imei{slot}")
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True, side_effect=Exception("unreachable"))
    assert register(show_spinner=True, register_konik=True) is None
    assert 60 <= now[0] < 75
    assert m.call_count > 1
    spinner.return_value.close.assert_called_once()
    assert self.params.get("DongleId") == "DONGLE_ID_123"
    assert self.params.get("KonikDongleId") is None

  def test_konik_registration_succeeds_after_failures(self, mocker):
    self._generate_keys()
    self._fake_clock(mocker)
    mocker.patch("openpilot.system.athena.registration.HARDWARE.get_imei", side_effect=lambda slot: f"imei{slot}")
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    m.side_effect = [Exception("down"), Exception("down"), MockResponse(json.dumps({'dongle_id': "KONIK_ID"}), 200)]
    assert register(register_konik=True) == "KONIK_ID"

  def test_stock_registration_keeps_retrying(self, mocker):
    # only the Konik path is bounded
    self._generate_keys()
    now = self._fake_clock(mocker)
    mocker.patch("openpilot.system.athena.registration.HARDWARE.get_imei", side_effect=lambda slot: f"imei{slot}")
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    m.side_effect = [Exception("down")] * 30 + [MockResponse(json.dumps({'dongle_id': "DONGLE_ID_123"}), 200)]
    assert register() == "DONGLE_ID_123"
    assert now[0] > 60

  def test_imei_is_used_when_available(self, mocker):
    self._generate_keys()
    mocker.patch("openpilot.system.athena.registration.HARDWARE.get_imei", side_effect=lambda slot: f"imei{slot}")
    m = mocker.patch("openpilot.system.athena.registration.api_get", autospec=True)
    m.return_value = MockResponse(json.dumps({'dongle_id': "DONGLE_ID_123"}), 200)
    register()
    assert (m.call_args.kwargs["imei"], m.call_args.kwargs["imei2"]) == ("imei0", "imei1")
