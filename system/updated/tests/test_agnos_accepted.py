import subprocess
from pathlib import Path

import pytest

from openpilot.common.basedir import BASEDIR
from openpilot.system.updated import updated


def _launch_env(**env):
  return subprocess.run(["bash", "-c", "source launch_env.sh && echo -n \"$AGNOS_VERSION|$AGNOS_ACCEPTED_VERSIONS\""], cwd=BASEDIR,
                        capture_output=True, text=True, check=True,
                        env={"PATH": "/usr/bin:/bin", **env}).stdout.split("|")


def test_launch_env_accepts_the_clone_os_versions_by_default():
  version, accepted = _launch_env()
  assert version in accepted.split()
  assert "13.1" in accepted.split() and "19.7" in accepted.split()


def test_launch_env_respects_an_explicit_list():
  _, accepted = _launch_env(AGNOS_ACCEPTED_VERSIONS="19.6.20")
  assert accepted == "19.6.20"


def test_no_agnos_flash_flag_is_checked_before_the_verify_step():
  src = (Path(BASEDIR) / "launch_chffrplus.sh").read_text()
  assert src.index("/data/NO_AGNOS_FLASH") < src.index('"$AGNOS_UPDATE_REQUIRED" = "1"')


@pytest.mark.parametrize("current,accepted,flashes", [
  ("19.6.20", ["19.6.20", "13.1"], False),   # already on the target
  ("13.1", ["19.6.20", "13.1"], False),      # clone on an accepted older OS
  ("13.1", ["19.6.20"], True),               # no accepted list covering it: a normal update
  ("12.8", ["19.6.20", "13.1"], True),
])
def test_handle_agnos_update(mocker, current, accepted, flashes):
  agnos = pytest.importorskip("openpilot.system.hardware.tici.agnos")
  flash = mocker.patch.object(agnos, "flash_agnos_update")
  mocker.patch.object(agnos, "get_target_slot_number", return_value=1)
  mocker.patch.object(updated.HARDWARE, "get_os_version", return_value=current, create=True)
  mocker.patch.object(updated, "set_consistent_flag")
  mocker.patch.object(updated, "set_offroad_alert")

  def fake_run(cmd, cwd=None):
    assert "launch_env.sh" in cmd[-1]
    return "19.6.20" if "echo -n $AGNOS_VERSION" in cmd[-1] else " ".join(accepted)
  mocker.patch.object(updated, "run", side_effect=fake_run)

  updated.handle_agnos_update()
  assert flash.called == flashes
