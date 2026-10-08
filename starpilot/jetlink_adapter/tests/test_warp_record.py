"""A warp pickle is only as good as the tinygrad that captured it: the record the build writes beside it, and the refusal
of a pickle whose record does not match this tree."""
import json
import subprocess
import types
from pathlib import Path

import pytest

from jetlink.openpilot.warp import Warps
from openpilot.starpilot import jetlink_adapter as ja
from openpilot.starpilot.jetlink_adapter import build_warp

GEOMETRY = (1928, 1208, 512, 256)


@pytest.fixture
def warp_dir(monkeypatch, tmp_path):
  monkeypatch.setattr(ja, "WARP_DIR", tmp_path)
  return tmp_path


def make_pickle(warp_dir, meta=None, **overrides):
  path = ja.warp_path(*GEOMETRY)
  path.write_bytes(b"not a real pickle; only its presence and record are under test")
  if meta is not False:
    record = {**ja.warp_meta(*GEOMETRY), **overrides} if meta is None else meta
    ja.warp_meta_path(path).write_text(json.dumps(record))
  return path


def test_the_record_names_the_tinygrad_pin_and_the_jetlink_version():
  meta = ja.warp_meta(*GEOMETRY)
  assert meta["tinygrad_commit"] == "f6fc4e3f2c3db5fae1e19cbfbc3ad9fc579a12ae" == ja.tinygrad_commit()
  assert meta["jetlink_version"] == "0.8.5"
  import jetlink
  assert ja.jetlink_version() == jetlink.__version__


def test_no_pickle_is_not_a_stale_one(warp_dir):
  assert ja.warp_problem(*GEOMETRY) is None
  assert ja.Adapter().warp_path(*GEOMETRY) == ja.warp_path(*GEOMETRY)
  assert Warps(ja.Adapter()).is_cached(*GEOMETRY) is False


def test_a_pickle_with_a_matching_record_is_offered_to_jetlink(warp_dir):
  make_pickle(warp_dir)
  assert ja.warp_problem(*GEOMETRY) is None
  assert Warps(ja.Adapter()).is_cached(*GEOMETRY) is True


def test_a_pickle_with_no_record_is_refused(warp_dir):
  make_pickle(warp_dir, meta=False)
  assert "no build record" in ja.warp_problem(*GEOMETRY)
  assert Warps(ja.Adapter()).is_cached(*GEOMETRY) is False


@pytest.mark.parametrize("key,value", [("tinygrad_commit", "0" * 40), ("jetlink_version", "0.1.0"), ("camera", [1344, 760]),
                                       ("model", [1, 1]), ("api", 99)])
def test_a_pickle_built_against_anything_else_is_refused_and_says_what(warp_dir, key, value):
  make_pickle(warp_dir, **{key: value})
  problem = ja.warp_problem(*GEOMETRY)
  assert problem and key in problem and "build_warp.py" in problem
  assert Warps(ja.Adapter()).is_cached(*GEOMETRY) is False


def test_the_driver_is_told_to_rebuild_not_that_nothing_was_built(warp_dir, monkeypatch, tmp_path):
  params = tmp_path / "params"
  (params / "d").mkdir(parents=True)
  (params / "d" / ja.KEYS.link).write_text("1")
  monkeypatch.setenv("PARAMS_ROOT", str(params))
  monkeypatch.delenv("OPENPILOT_PREFIX", raising=False)
  monkeypatch.setattr(ja, "_bound", types.SimpleNamespace(reason=lambda: "no warp built for this camera"))
  monkeypatch.setattr(ja.Adapter, "camera", lambda self: GEOMETRY)
  assert "turn Jetlink off" in ja.reason()                 # never built
  make_pickle(warp_dir, tinygrad_commit="0" * 40)
  assert "tinygrad_commit" in ja.reason() and "rebuild" in ja.reason()


def test_the_build_script_writes_the_record_that_the_check_accepts(warp_dir, monkeypatch):
  built = []

  def fake_run(cmd, **kwargs):
    if "jetlink.openpilot.warp" in cmd:
      Path(cmd[cmd.index("--output") + 1]).write_bytes(b"pickle")
      built.append(cmd)
    return subprocess.CompletedProcess(cmd, 0)
  monkeypatch.setattr(build_warp.subprocess, "run", fake_run)
  monkeypatch.setattr(ja.Adapter, "camera", lambda self: GEOMETRY)
  assert build_warp.main(["--camera", "1928x1208"]) == 0
  assert len(built) == 1 and "--adapter" in built[0] and ja.ADAPTER_MODULE in built[0]
  assert ja.warp_problem(*GEOMETRY) is None
  assert json.loads(ja.warp_meta_path(ja.warp_path(*GEOMETRY)).read_text()) == ja.warp_meta(*GEOMETRY)


def test_a_failed_build_leaves_no_record_and_a_nonzero_exit(warp_dir, monkeypatch):
  monkeypatch.setattr(build_warp.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1))
  monkeypatch.setattr(ja.Adapter, "camera", lambda self: GEOMETRY)
  assert build_warp.main(["--camera", "1928x1208"]) == 1
  assert not ja.warp_meta_path(ja.warp_path(*GEOMETRY)).exists()
