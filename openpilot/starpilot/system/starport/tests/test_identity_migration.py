from pathlib import Path

import pytest

from openpilot.starpilot.system.starport import identity


@pytest.mark.parametrize('outcome', ['moved', 'concurrent', 'denied'])
def test_existing_identity_survives_directory_migration(tmp_path, monkeypatch, outcome):
  legacy, current = tmp_path / 'android_auto', tmp_path / 'starport'
  legacy.mkdir()
  (legacy / 'certificate').write_bytes(b'existing identity')
  monkeypatch.delenv('STARPORT_DIR', raising=False)
  monkeypatch.delenv('ANDROID_AUTO_DIR', raising=False)
  monkeypatch.setattr(identity, 'Path', lambda value: tmp_path / Path(value).name)
  rename = Path.rename

  def migrate(source, destination):
    if outcome == 'denied':
      raise PermissionError('directory is not writable')
    rename(source, destination)
    if outcome == 'concurrent':
      raise FileNotFoundError('another process already moved the directory')

  monkeypatch.setattr(Path, 'rename', migrate)

  directory = identity._data_dir()

  assert directory == (legacy if outcome == 'denied' else current)
  assert (directory / 'certificate').read_bytes() == b'existing identity'
