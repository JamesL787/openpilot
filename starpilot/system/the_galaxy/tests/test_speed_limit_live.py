from types import SimpleNamespace

from openpilot.starpilot.system.the_galaxy import the_galaxy


def _plan(limit_ms=0.0, pending_ms=0.0, source="Map Data"):
  return SimpleNamespace(slcSpeedLimit=limit_ms, unconfirmedSlcSpeedLimit=pending_ms, slcSpeedLimitSource=source)


def test_reports_the_accepted_limit_in_display_units():
  payload = the_galaxy.speed_limit_live_payload(_plan(limit_ms=24.5872, source="Mapbox"), is_metric=False)
  assert payload == {"available": True, "speedLimit": 55, "pendingSpeedLimit": 0, "unit": "mph", "source": "Mapbox", "reason": ""}

  metric = the_galaxy.speed_limit_live_payload(_plan(limit_ms=27.7778), is_metric=True)
  assert (metric["speedLimit"], metric["unit"]) == (100, "km/h")


def test_pending_limit_alone_is_not_available():
  payload = the_galaxy.speed_limit_live_payload(_plan(limit_ms=0.0, pending_ms=29.0576), is_metric=False)
  assert payload["available"] is False
  assert payload["pendingSpeedLimit"] == 65
  assert payload["reason"] == "No speed limit."


def test_no_plan_is_unavailable_and_says_why():
  assert the_galaxy.speed_limit_live_payload(None, is_metric=False)["available"] is False
  paused = the_galaxy.speed_limit_live_payload(None, is_metric=False, paused_reason="Plots is paused")
  assert paused["reason"] == "Plots is paused"
  assert paused["source"] == ""


def test_live_plan_never_opens_a_reader_offroad(monkeypatch):
  monkeypatch.setattr(the_galaxy, "_safe_params_get_bool", lambda key, *a, **k: False)
  monkeypatch.setattr(the_galaxy, "_get_drive_plots", lambda: (_ for _ in ()).throw(AssertionError("opened Plots offroad")))
  assert the_galaxy._live_starpilot_plan() is None


def test_live_plan_reads_through_plots_and_respects_pause(monkeypatch):
  class Plots:
    def __init__(self, paused):
      self.paused, self.touched = paused, 0
    def live_message(self, service, max_age_s=1.0):
      assert service == "starpilotPlan"
      return None
    def paused_reason(self):
      return self.paused
    def touch(self):
      self.touched += 1

  monkeypatch.setattr(the_galaxy, "_safe_params_get_bool", lambda key, *a, **k: key == "IsOnroad")
  paused = Plots("paused for Android Auto")
  monkeypatch.setattr(the_galaxy, "_get_drive_plots", lambda: paused)
  assert the_galaxy._live_starpilot_plan(wait_s=0.0) is None
  assert paused.touched == 0

  running = Plots("")
  monkeypatch.setattr(the_galaxy, "_get_drive_plots", lambda: running)
  assert the_galaxy._live_starpilot_plan(wait_s=0.0) is None
  assert running.touched == 1
