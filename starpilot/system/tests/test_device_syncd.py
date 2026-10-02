from openpilot.starpilot.system import device_syncd


class _Response:
  status_code = 200

  def __init__(self, payload):
    self._payload = payload

  def raise_for_status(self):
    pass

  def json(self):
    return self._payload


class _FakeParams:
  def __init__(self, values):
    self.values = dict(values)

  def get_bool(self, key):
    return self.values.get(key) == "1"

  def check_key(self, key):
    pass

  def cpp2python(self, key, value):
    return value.decode("utf-8")

  def put(self, key, value):
    self.values[key] = value

  def put_bool(self, key, value):
    self.values[key] = "1" if value else "0"


def test_server_toggles_cannot_undo_the_bosch_a_u11_scale72_migration(monkeypatch):
  # D-074: a server copy taken before the migration still holds "0" for both keys.
  payload = {"toggles": {"BoschAU11Scale72": "0", "BoschAU11Scale72Migrated": "0", "OtherToggle": "0"}}
  monkeypatch.setattr(device_syncd, "is_url_pingable", lambda url: True)
  monkeypatch.setattr(device_syncd, "get_starpilot_api_info", lambda: ("token", None, "device", "dongle"))
  monkeypatch.setattr(device_syncd, "_remote_request", lambda method, path, **kwargs: _Response(payload))
  monkeypatch.setattr(device_syncd, "update_starpilot_toggles", lambda: None)
  params = _FakeParams({device_syncd.GALAXY_PAIRED_PARAM: "1", "BoschAU11Scale72": "1",
                        "BoschAU11Scale72Migrated": "1", "OtherToggle": "1"})

  device_syncd.check_toggles(False, params, boot_run=True)

  assert params.values["BoschAU11Scale72"] == "1"
  assert params.values["BoschAU11Scale72Migrated"] == "1"
  assert params.values["OtherToggle"] == "0"  # the sync itself still runs


def test_sync_exclusion_does_not_touch_the_shared_excluded_keys():
  assert {"BoschAU11Scale72", "BoschAU11Scale72Migrated"} <= device_syncd.DEVICE_SYNC_EXCLUDED_KEYS
  assert "BoschAU11Scale72" not in device_syncd.EXCLUDED_KEYS
