"""What the driver is told, and when: JetlinkEvents on real starpilotModelV2 messages."""
import types


from cereal import custom, messaging
from openpilot.starpilot.controls.lib import jetlink_events as je

Name = custom.StarPilotOnroadEvent.EventName


class Events:
  def __init__(self):
    self.names = []

  def add(self, name):
    self.names.append(name)


class Sm:
  def __init__(self):
    self.seen = {"starpilotModelV2": True}
    self.alive = {"starpilotModelV2": True}
    self.valid = {"starpilotModelV2": True}
    self._reader = None
    self.set(backend="local", accelerator="none")

  def set(self, **fields):
    msg = messaging.new_message("starpilotModelV2")
    for k, v in fields.items():
      setattr(msg.starpilotModelV2, k, v)
    self._reader = messaging.log_from_bytes(msg.to_bytes()).starpilotModelV2

  def __getitem__(self, key):
    assert key == "starpilotModelV2"
    return self._reader


def run(j, sm, in_control, ticks=1):
  collected = []
  for _ in range(ticks):
    e = Events()
    j.update(sm, in_control, e)
    collected.append(list(e.names))
  return collected


def flat(collected):
  return [n for tick in collected for n in tick]


def test_enum_values_compare_the_way_the_events_read_them():
  sm = Sm()
  sm.set(backend="jetlink", accelerator="running")
  assert sm["starpilotModelV2"].backend == je.Backend.jetlink
  assert sm["starpilotModelV2"].accelerator == je.AcceleratorState.running


def test_ready_while_engaged_offers_the_switch_once():
  j, sm = je.JetlinkEvents(), Sm()
  sm.set(backend="local", accelerator="ready")
  ticks = run(j, sm, True, je.OFFER_TICKS + 50)
  assert flat(ticks).count(Name.jetlinkAvailable) == je.OFFER_TICKS            # once, for its duration
  assert ticks[0] == [Name.jetlinkAvailable] and ticks[-1] == []


def test_ready_with_nothing_in_control_offers_nothing_because_it_swaps_at_once():
  j, sm = je.JetlinkEvents(), Sm()
  sm.set(backend="local", accelerator="ready")
  assert flat(run(j, sm, False, 20)) == []


def test_the_offer_is_withdrawn_when_the_link_goes():
  j, sm = je.JetlinkEvents(), Sm()
  sm.set(accelerator="ready")
  run(j, sm, True, 5)
  sm.set(accelerator="retrying")
  assert flat(run(j, sm, True, 5)) == []
  assert j.offer == 0


def test_a_swap_in_refuses_engagement_for_a_second_then_chimes():
  j, sm = je.JetlinkEvents(), Sm()
  run(j, sm, False, 3)
  sm.set(backend="jetlink", accelerator="running")
  ticks = run(j, sm, False, je.SWITCHING_TICKS + 5)
  assert ticks[0] == [Name.jetlinkSwitching]
  assert all(t == [Name.jetlinkSwitching] for t in ticks[:je.SWITCHING_TICKS])
  assert ticks[je.SWITCHING_TICKS] == [Name.jetlinkReady]
  assert flat(ticks).count(Name.jetlinkReady) == 1 and ticks[-1] == []
  assert not j.settling


def test_settling_covers_the_second_after_a_swap_in_and_a_handback():
  j, sm = je.JetlinkEvents(), Sm()
  sm.set(backend="jetlink", accelerator="running")
  run(j, sm, False, 1)
  assert j.settling
  run(j, sm, False, je.SWITCHING_TICKS + 2)
  assert not j.settling
  sm.set(backend="local", accelerator="retrying")
  run(j, sm, False, 1)
  assert j.settling
  run(j, sm, False, je.SWITCHING_TICKS + 2)
  assert not j.settling


def test_a_handback_while_engaged_warns_for_five_seconds_and_disengages_nothing():
  j, sm = je.JetlinkEvents(), Sm()
  sm.set(backend="jetlink", accelerator="running")
  run(j, sm, True, je.SWITCHING_TICKS + 5)
  sm.set(backend="local", accelerator="retrying")
  ticks = run(j, sm, True, je.HANDBACK_TICKS + 5)
  assert flat(ticks).count(Name.jetlinkLinkLost) == je.HANDBACK_TICKS
  assert Name.jetlinkSwitching not in flat(ticks)          # a handback is never a no-entry


def test_a_handback_with_nobody_in_control_is_silent():
  j, sm = je.JetlinkEvents(), Sm()
  sm.set(backend="jetlink", accelerator="running")
  run(j, sm, False, je.SWITCHING_TICKS + 5)
  sm.set(backend="local", accelerator="retrying")
  assert Name.jetlinkLinkLost not in flat(run(j, sm, False, 20))


def test_stale_status_neither_offers_nor_rearms():
  j, sm = je.JetlinkEvents(), Sm()
  sm.set(accelerator="ready")
  sm.alive["starpilotModelV2"] = False
  assert flat(run(j, sm, True, 30)) == []
  sm.alive["starpilotModelV2"] = True
  assert flat(run(j, sm, True, 3))[:1] == [Name.jetlinkAvailable]


def test_modeld_going_quiet_ends_a_running_backend_as_a_handback():
  j, sm = je.JetlinkEvents(), Sm()
  sm.set(backend="jetlink", accelerator="running")
  run(j, sm, True, 5)
  sm.alive["starpilotModelV2"] = False
  assert Name.jetlinkLinkLost in flat(run(j, sm, True, 3))


def test_every_event_has_an_alert_and_the_switch_is_a_no_entry():
  # the StarPilot table, not EVENTS: the two enums' integers overlap
  from openpilot.selfdrive.selfdrived.events import STARPILOT_EVENTS, ET
  for name in (Name.jetlinkAvailable, Name.jetlinkSwitching, Name.jetlinkReady, Name.jetlinkLinkLost):
    assert name in STARPILOT_EVENTS, name
  assert ET.NO_ENTRY in STARPILOT_EVENTS[Name.jetlinkSwitching]
  for name in (Name.jetlinkAvailable, Name.jetlinkReady, Name.jetlinkLinkLost):
    assert not {ET.SOFT_DISABLE, ET.IMMEDIATE_DISABLE, ET.USER_DISABLE} & set(STARPILOT_EVENTS[name]), name   # informing, never disabling


def test_jetlinkd_is_optional_to_selfdrived():
  assert "jetlinkd" in je.OPTIONAL_PROCESSES


class TestSelfdrivedUses:
  def test_a_dead_optional_process_is_not_process_not_running(self):
    import ast
    from pathlib import Path
    src = (Path(__file__).resolve().parents[3] / "selfdrive/selfdrived/selfdrived.py").read_text()
    tree = ast.parse(src)
    comps = [n for n in ast.walk(tree) if isinstance(n, ast.SetComp) and "shouldBeRunning" in ast.unparse(n)]
    assert comps and all("OPTIONAL_PROCESSES" in ast.unparse(c) for c in comps)

  def test_the_pose_events_are_held_back_only_while_settling_and_the_suppression_is_logged(self, monkeypatch):
    from openpilot.selfdrive.selfdrived import selfdrived as sd
    logged = []
    monkeypatch.setattr(sd.cloudlog, "event", lambda name, **kw: logged.append(name))
    events = Events()
    me = types.SimpleNamespace(jetlink_events=types.SimpleNamespace(settling=True), jetlink_pose_suppressed=False, events=events)
    add = sd.SelfdriveD.add_pose_event
    add(me, "posenetInvalid")
    add(me, "locationdTemporaryError")
    assert events.names == [] and logged == ["jetlink_settling_suppressed"]     # nothing added, one log line per window
    me.jetlink_events.settling = False
    add(me, "posenetInvalid")
    assert events.names == ["posenetInvalid"]                                   # a real fault outside the window shows
