from openpilot.starpilot.system.starpilot_auto import identity


class FakeParams:
  """Strict like the real Params: BOOL keys take put_bool only, and the retired key is unregistered."""

  def __init__(self, tmp_path, legacy=None, current=None):
    self.tmp_path = tmp_path
    self.values = {} if current is None else {identity.ENABLED_KEY: current}
    if legacy is not None:
      (tmp_path / identity.LEGACY_ENABLED_KEY).write_bytes(legacy)

  def get(self, key, **_):
    if key == identity.LEGACY_ENABLED_KEY:
      raise KeyError(key)
    return self.values.get(key)

  def put(self, key, value):
    raise TypeError(f"{key} is a BOOL param; use put_bool")

  def put_bool(self, key, value):
    assert isinstance(value, bool)
    self.values[key] = value

  def get_param_path(self, key=""):
    return str(self.tmp_path / key)


def migrate(tmp_path, params):
  identity.migrate_legacy(data_dir=tmp_path / "data", legacy_dir=tmp_path / "legacy", params=params)


def test_migrates_enabled_flag_once_and_removes_the_legacy_file(tmp_path):
  params = FakeParams(tmp_path, legacy=b"1")
  migrate(tmp_path, params)
  assert params.values[identity.ENABLED_KEY] is True
  assert not (tmp_path / identity.LEGACY_ENABLED_KEY).exists()
  (tmp_path / identity.LEGACY_ENABLED_KEY).write_bytes(b"0")
  migrate(tmp_path, params)
  assert params.values[identity.ENABLED_KEY] is True


def test_migrates_a_disabled_flag_as_false(tmp_path):
  params = FakeParams(tmp_path, legacy=b"0")
  migrate(tmp_path, params)
  assert params.values[identity.ENABLED_KEY] is False


def test_skips_params_migration_when_already_set(tmp_path):
  params = FakeParams(tmp_path, legacy=b"1", current=False)
  migrate(tmp_path, params)
  assert params.values[identity.ENABLED_KEY] is False


def test_no_legacy_flag_leaves_the_setting_unset(tmp_path):
  params = FakeParams(tmp_path)
  migrate(tmp_path, params)
  assert identity.ENABLED_KEY not in params.values


def test_migrates_data_directory(tmp_path):
  data, legacy = tmp_path / "data", tmp_path / "legacy"
  (legacy / "identity").mkdir(parents=True)
  (legacy / "identity" / identity.CERT_NAME).write_text("cert")
  (legacy / "identity" / identity.KEY_NAME).write_text("key")
  (legacy / identity.CONFIG_PATH.name).write_text("{}")
  (legacy / "identity.previous").mkdir()
  identity.migrate_legacy(data_dir=data, legacy_dir=legacy, params=FakeParams(tmp_path))
  assert (data / "identity" / identity.CERT_NAME).read_text() == "cert"
  assert (data / "identity.previous").is_dir()
  assert (data / identity.CONFIG_PATH.name).exists()
  assert not legacy.exists()


def test_keeps_existing_data_and_moves_only_missing(tmp_path):
  data, legacy = tmp_path / "data", tmp_path / "legacy"
  (data / "identity").mkdir(parents=True)
  (data / "identity" / identity.CERT_NAME).write_text("new")
  (legacy / "identity").mkdir(parents=True)
  (legacy / "identity" / identity.CERT_NAME).write_text("old")
  (legacy / "logs").mkdir()
  (legacy / "logs" / "session-000001-x.jsonl").write_text("{}")
  identity.migrate_legacy(data_dir=data, legacy_dir=legacy, params=FakeParams(tmp_path))
  assert (data / "identity" / identity.CERT_NAME).read_text() == "new"
  assert (data / "logs" / "session-000001-x.jsonl").exists()
  assert (legacy / "identity" / identity.CERT_NAME).read_text() == "old"


def test_nothing_to_migrate(tmp_path):
  data, legacy = tmp_path / "data", tmp_path / "legacy"
  identity.migrate_legacy(data_dir=data, legacy_dir=legacy, params=FakeParams(tmp_path))
  assert not data.exists() and not legacy.exists()


def test_env_override_skips_data_migration(tmp_path, monkeypatch):
  monkeypatch.setenv("STARPILOT_AUTO_DIR", str(tmp_path / "custom"))
  legacy = tmp_path / "legacy"
  legacy.mkdir()
  (legacy / "extra").write_text("x")
  identity.migrate_legacy(legacy_dir=legacy, params=FakeParams(tmp_path))
  assert (legacy / "extra").exists()


class UploadParams:
  def __init__(self, **values):
    self.values = values

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def put_bool(self, key, value):
    assert isinstance(value, bool)
    self.values[key] = value


def test_devices_already_using_starpilot_auto_get_the_upload_settings_once(tmp_path):
  marker = tmp_path / "data" / "upload_settings_applied"
  params = UploadParams(**{identity.ENABLED_KEY: True, "NoUploads": False, "AlwaysAllowUploads": True})
  assert identity.apply_upload_settings_once(params, marker)
  assert {key: params.values[key] for key in identity.UPLOAD_SETTINGS} == identity.UPLOAD_SETTINGS
  assert marker.exists()

  params.values["NoUploads"] = False  # the tester chooses to allow uploads again
  assert not identity.apply_upload_settings_once(params, marker)
  assert params.values["NoUploads"] is False, "a later choice is kept"


def test_upload_settings_are_left_alone_when_starpilot_auto_is_off(tmp_path):
  marker = tmp_path / "upload_settings_applied"
  params = UploadParams(**{identity.ENABLED_KEY: False, "NoUploads": False})
  assert not identity.apply_upload_settings_once(params, marker)
  assert params.values == {identity.ENABLED_KEY: False, "NoUploads": False} and marker.exists()
