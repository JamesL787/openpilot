import os

from openpilot.common.params import Params
import openpilot.system.manager.manager as manager

OLD_TO_NEW = {
  "NrdrLatEpsFirmwareFF": "HondaEpsController",
  "NrdrLatUseFirmwareVgr": "HondaEpsFirmwareVgr",
  "NrdrLatAngleRateLimit": "HondaEpsAngleRateLimit",
}


def _write_legacy(params, key, raw: bytes):
  # the old keys are no longer registered, so write their files the way an older build left them
  path = params.get_param_path(key)
  os.makedirs(os.path.dirname(path), exist_ok=True)
  with open(path, "wb") as f:
    f.write(raw)
  return path


def test_old_nrdr_keys_carry_over_to_honda_eps_once(tmp_path, monkeypatch):
  monkeypatch.setattr(manager, "HONDA_EPS_PARAM_RENAME_MIGRATION_FLAG", tmp_path / "honda_eps_param_rename_v1")
  params = Params()
  for new in OLD_TO_NEW.values():
    params.remove(new)
  paths = [_write_legacy(params, "NrdrLatEpsFirmwareFF", b"1"),
           _write_legacy(params, "NrdrLatUseFirmwareVgr", b"1"),
           _write_legacy(params, "NrdrLatAngleRateLimit", b"219")]

  manager.migrate_honda_eps_param_names(params, params)

  assert params.get_bool("HondaEpsController") and params.get_bool("HondaEpsFirmwareVgr")
  assert params.get("HondaEpsAngleRateLimit") == 219
  assert not any(os.path.isfile(p) for p in paths)          # the old files are gone
  assert (tmp_path / "honda_eps_param_rename_v1").exists()

  # a later boot does not touch a value the owner has since changed
  params.put_bool("HondaEpsController", False)
  _write_legacy(params, "NrdrLatEpsFirmwareFF", b"1")
  manager.migrate_honda_eps_param_names(params, params)
  assert not params.get_bool("HondaEpsController")


def test_an_existing_new_key_wins_over_a_stale_old_one(tmp_path, monkeypatch):
  monkeypatch.setattr(manager, "HONDA_EPS_PARAM_RENAME_MIGRATION_FLAG", tmp_path / "honda_eps_param_rename_v1")
  params = Params()
  params.put("HondaEpsAngleRateLimit", 500)
  old = _write_legacy(params, "NrdrLatAngleRateLimit", b"219")
  manager.migrate_honda_eps_param_names(params, params)
  assert params.get("HondaEpsAngleRateLimit") == 500
  assert not os.path.isfile(old)
