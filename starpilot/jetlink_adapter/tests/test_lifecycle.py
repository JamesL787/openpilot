"""manager: the optional owner process, its restart backoff, and the bounded host shutdown."""
import types

import pytest

from openpilot.starpilot import jetlink_adapter as ja
from openpilot.system.manager import process as proc_mod
from openpilot.system.manager.accelerator_shutdown import AcceleratorShutdown
from openpilot.system.manager.process import OptionalPythonProcess, ensure_running


class FakeProc:
  def __init__(self):
    self.exitcode = None
    self.pid = 4242

  def is_alive(self):
    return self.exitcode is None

  def join(self, timeout=None):
    pass


class Clock:
  def __init__(self):
    self.t = 100.0

  def __call__(self):
    return self.t


@pytest.fixture
def owner(monkeypatch):
  clock = Clock()
  started = []

  def fake_start(self):
    # PythonProcess.start: reap a process that was being stopped, then start one if none is running
    if self.shutting_down:
      self.stop()
    if self.proc is None:
      self.proc = FakeProc()
      started.append(clock.t)
  monkeypatch.setattr(proc_mod.PythonProcess, "start", fake_start)
  monkeypatch.setattr(proc_mod, "join_process", lambda p, t: None)
  p = OptionalPythonProcess("jetlinkd", "starpilot.jetlink_adapter", lambda *a: True)
  p.now = clock
  return p, clock, started


def loop(p):
  return ensure_running([p], True, params=None, CP=None, starpilot_toggles=None)


class TestRestartBackoff:
  def test_it_starts_and_a_long_run_that_dies_restarts_at_once(self, owner):
    p, clock, started = owner
    loop(p)
    clock.t += 60
    p.proc.exitcode = 1
    loop(p)                                    # reaped and started again in the same loop
    assert len(started) == 2 and p.backoff == 0

  def test_one_that_dies_young_waits_and_the_wait_doubles_to_a_cap(self, owner):
    p, clock, started = owner
    loop(p)
    waits = []
    for _ in range(8):
      clock.t += 1
      p.proc.exitcode = 1
      loop(p)
      waits.append(p.backoff)
      assert p.proc is None                    # not started again yet
      clock.t = p.next_start                   # the wait is over
      loop(p)
      assert p.proc is not None
    assert waits[:3] == [10.0, 20.0, 40.0] and max(waits) == OptionalPythonProcess.BACKOFF_MAX

  def test_the_wait_is_honoured_until_it_is_over(self, owner):
    p, clock, started = owner
    loop(p)
    clock.t += 1
    p.proc.exitcode = 1
    loop(p)
    for _ in range(5):
      clock.t += 1
      loop(p)
      assert p.proc is None and len(started) == 1
    clock.t = p.next_start
    loop(p)
    assert len(started) == 2

  def test_stopping_a_live_process_is_not_a_death(self, owner, monkeypatch):
    p, clock, started = owner
    signalled = []
    monkeypatch.setattr(proc_mod.os, "kill", lambda pid, sig: signalled.append(sig))
    loop(p)
    p.should_run = lambda *a: False                  # the user turned the link off
    ensure_running([p], True, params=None, CP=None, starpilot_toggles=None)
    assert signalled and p.backoff == 0 and p.next_start == 0.0
    p.proc.exitcode = 0                              # it exits cleanly on the signal
    p.should_run = lambda *a: True                   # and the user turns it back on: started at once, no wait
    loop(p)
    assert len(started) == 2

  def test_a_death_after_a_backoff_that_then_ran_long_resets_it(self, owner):
    p, clock, started = owner
    loop(p)
    clock.t += 1
    p.proc.exitcode = 1
    loop(p)
    clock.t = p.next_start
    loop(p)
    clock.t += 120
    p.proc.exitcode = 1
    loop(p)
    assert p.backoff == 0 and p.proc is not None


class TestProcessConfig:
  def test_jetlinkd_is_registered_as_an_optional_process(self):
    from openpilot.system.manager.process_config import managed_processes
    p = managed_processes[ja.OWNER]
    assert isinstance(p, OptionalPythonProcess) and p.module == "starpilot.jetlink_adapter"

  def test_it_runs_while_the_link_is_on_offroad_and_onroad_and_never_with_the_link_off(self, monkeypatch, tmp_path):
    from openpilot.system.manager.process_config import managed_processes
    p = managed_processes[ja.OWNER]
    (tmp_path / "d").mkdir()
    monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENPILOT_PREFIX", raising=False)
    monkeypatch.setattr(ja, "_bound", types.SimpleNamespace(enabled=lambda: True))
    (tmp_path / "d" / ja.KEYS.link).write_text("1")
    assert p.should_run(False, None, None, None) is True and p.should_run(True, None, None, None) is True
    (tmp_path / "d" / ja.KEYS.link).write_text("0")
    assert p.should_run(False, None, None, None) is False and p.should_run(True, None, None, None) is False

  def test_a_chestnut_keeps_it_off_whatever_the_setting_says(self, monkeypatch, tmp_path):
    from openpilot.system.manager.process_config import managed_processes
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / ja.KEYS.link).write_text("1")
    monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENPILOT_PREFIX", raising=False)
    # Jetlink's own enabled(): the setting is on and no Chestnut is fitted
    from jetlink.openpilot import Jetlink
    from jetlink.openpilot.parts import Parts
    op = ja.Adapter()
    op.chestnut_present = lambda: True
    monkeypatch.setattr(ja, "_bound", Jetlink(Parts(op)))
    assert managed_processes[ja.OWNER].should_run(True, None, None, None) is False
    op.chestnut_present = lambda: False
    monkeypatch.setattr(ja, "_bound", Jetlink(Parts(op)))
    assert managed_processes[ja.OWNER].should_run(True, None, None, None) is True


class TestBoundedShutdown:
  def make(self, request, pending, timeout=25.0):
    clock = Clock()
    return AcceleratorShutdown(request, pending, clock, timeout), clock

  def test_with_nothing_to_ask_it_goes_down_at_once(self):
    s, _ = self.make(lambda reason: False, lambda: pytest.fail("polled"))
    assert s.ready("DoShutdown set") is True

  def test_it_asks_once_and_goes_down_when_the_request_is_taken(self):
    asked, state = [], {"pending": True}
    s, clock = self.make(lambda reason: asked.append(reason) or True, lambda: state["pending"])
    assert s.ready("x") is False
    clock.t += 5
    assert s.ready("x") is False
    state["pending"] = False
    assert s.ready("x") is True
    assert asked == ["x"]

  def test_nobody_taking_it_costs_the_timeout_and_no_more(self):
    s, clock = self.make(lambda reason: True, lambda: True, timeout=25.0)
    assert s.ready("x") is False
    clock.t += 24.9
    assert s.ready("x") is False
    clock.t += 0.2
    assert s.ready("x") is True

  def test_a_failing_request_or_poll_never_holds_the_shutdown(self):
    def boom(*a):
      raise RuntimeError("x")
    s, _ = self.make(boom, lambda: True)
    assert s.ready("x") is True
    s, _ = self.make(lambda reason: True, boom)
    assert s.ready("x") is True

  def test_the_defaults_are_the_adapters_hooks(self):
    import inspect
    sig = inspect.signature(AcceleratorShutdown.__init__)
    assert sig.parameters["request"].default is ja.request_shutdown and sig.parameters["pending"].default is ja.shutdown_pending

  def test_manager_waits_only_for_a_power_off_and_keeps_its_loop_running(self):
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[3] / "system/manager/manager.py").read_text()
    assert 'shutdown_param != "DoShutdown" or accelerator_shutdown.ready(' in src
    tree = ast.parse(src)
    loops = [n for n in ast.walk(tree) if isinstance(n, ast.If) and "accelerator_shutdown.ready" in ast.unparse(n.test)]
    assert loops and isinstance(loops[0].body[0], ast.Break)


class TestHardwared:
  def test_the_offroad_alert_is_declared_and_driven_by_the_adapters_reason(self):
    import json
    from pathlib import Path
    repo = Path(__file__).resolve().parents[3]
    alerts = json.loads((repo / "selfdrive/selfdrived/alerts_offroad.json").read_text())
    assert "%1" in alerts["Offroad_JetlinkUnavailable"]["text"]
    src = (repo / "system/hardware/hardwared.py").read_text()
    assert 'jetlink_adapter.reason()' in src and '"Offroad_JetlinkUnavailable"' in src

  def test_an_unusable_enabled_link_gets_an_actionable_reason(self, monkeypatch, tmp_path):
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / ja.KEYS.link).write_text("1")
    monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENPILOT_PREFIX", raising=False)
    monkeypatch.setattr(ja, "_bound", types.SimpleNamespace(reason=lambda: "no warp built for this camera"))
    assert "turn Jetlink off" in ja.reason()
    monkeypatch.setattr(ja, "_bound", types.SimpleNamespace(reason=lambda: "service stopped"))
    assert ja.reason() == "service stopped"


class TestNoDriveStartsUnderTheWait:
  def test_the_wait_is_published_for_hardwared_and_stays_set_on_every_way_out(self):
    marks = []
    clock = Clock()
    s = AcceleratorShutdown(lambda r: True, lambda: False, clock, 25.0, mark=marks.append)
    assert s.ready("x") is True and marks == [True]          # taken at once: still set, the device is going down
    marks.clear()
    s = AcceleratorShutdown(lambda r: False, lambda: True, clock, 25.0, mark=marks.append)
    assert s.ready("x") is True and marks == []              # nothing to ask: no wait, no mark

  def test_a_failing_mark_never_holds_the_shutdown(self):
    def boom(value):
      raise RuntimeError("x")
    s = AcceleratorShutdown(lambda r: True, lambda: False, Clock(), 25.0, mark=boom)
    assert s.ready("x") is True

  def test_hardwared_refuses_to_start_a_drive_while_it_is_set(self):
    from pathlib import Path
    src = (Path(__file__).resolve().parents[3] / "system/hardware/hardwared.py").read_text()
    assert 'startup_conditions["not_powering_off"] = not params.get_bool("JetlinkPoweringOff")' in src

  def test_the_key_is_declared_and_cleared_when_manager_starts(self):
    from pathlib import Path
    line = next(ln for ln in (Path(__file__).resolve().parents[3] / "common/params_keys.h").read_text().splitlines()
                if '"JetlinkPoweringOff"' in ln)
    assert "CLEAR_ON_MANAGER_START" in line and "BOOL" in line
