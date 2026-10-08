"""The qualification report, on a synthetic drive with one handover: it must find the switch, split the loop times by backend,
and judge the radar/plan steps around it against the rest of the drive."""
from cereal import messaging
from openpilot.starpilot.jetlink_adapter import route_report as rr

HANDOVER_AT = 10.0


def drive(lead_jump_at_handover=False, held_frames=0, disable=False):
  out = []

  def add(which, t, fill):
    m = messaging.new_message(which)
    m.logMonoTime = int(t * 1e9)
    fill(getattr(m, which))
    out.append(messaging.log_from_bytes(m.to_bytes()))

  for i in range(400):        # 20 s at 20 Hz
    t = i * 0.05
    remote = t >= HANDOVER_AT
    add("starpilotModelV2", t, lambda s, remote=remote, i=i: (
      setattr(s, "backend", "jetlink" if remote else "local"), setattr(s, "accelerator", "running" if remote else "ready"),
      setattr(s, "heldFrames", held_frames if remote and i % 7 == 0 else 0),
      setattr(s, "outputAgeMs", 50.0 * held_frames if remote and i % 7 == 0 else 0.0)))

    def fill_model(v, t=t, i=i, remote=remote):
      v.frameId = i + (3 if remote and i > 205 else 0)       # a camera frame dropped after the swap
      v.modelExecutionTime = (0.040 if remote else 0.020) + (0.0005 * (i % 5))
      v.frameDropPerc = 0.0
      v.velocity.x = [20.0 + 0.001 * i] * 33
      v.leadsV3 = [{"prob": 0.9}, {"prob": 0.0}, {"prob": 0.0}]
    add("modelV2", t + 0.001, fill_model)

    def fill_radar(r, t=t, i=i):
      jump = 6.0 if lead_jump_at_handover and abs(t - HANDOVER_AT) < 0.03 else 0.0
      r.mdMonoTime = int((t + 0.001) * 1e9)
      r.leadOne.status = True
      r.leadOne.dRel = 40.0 - 0.5 * t + jump
      r.leadOne.vRel = -1.0
      r.leadOne.modelProb = 0.9
    add("radarState", t + 0.003, fill_radar)
    add("longitudinalPlan", t + 0.004, lambda p, t=t: setattr(p, "aTarget", 0.1 * (1 if int(t) % 2 else -1) * 0.01))
  if disable:
    m = messaging.new_message("onroadEvents", 1)
    m.logMonoTime = int((HANDOVER_AT + 0.5) * 1e9)
    m.onroadEvents[0].name = "posenetInvalid"
    m.onroadEvents[0].softDisable = True
    out.append(messaging.log_from_bytes(m.to_bytes()))
  return out


def test_it_finds_the_handover_and_splits_loop_times_by_backend():
  report = rr.analyze(drive())
  assert [(h["from"], h["to"]) for h in report["handovers"]] == [("local", "jetlink")]
  assert abs(report["handovers"][0]["t"] - HANDOVER_AT) < 0.06
  local, remote = report["by_backend"]["local"], report["by_backend"]["jetlink"]
  assert local["exec_ms"]["p50"] < remote["exec_ms"]["p50"]
  assert 19 < local["exec_ms"]["p50"] < 23 and 39 < remote["exec_ms"]["p50"] < 43
  assert remote["dropped_camera_frames"] == 3 and local["dropped_camera_frames"] == 0


def test_a_quiet_handover_stays_within_the_drives_own_step_statistics():
  report = rr.analyze(drive())
  h = report["handovers"][0]
  assert h["lead_range_jumps"] == 0 and h["lead_status_flips"] == 0
  assert not h["around"]["lead_range_m"]["exceeds_baseline"]


def test_a_lead_range_jump_at_the_handover_is_flagged_against_the_baseline():
  report = rr.analyze(drive(lead_jump_at_handover=True))
  h = report["handovers"][0]
  assert h["lead_range_jumps"] >= 1
  assert h["around"]["lead_range_m"]["exceeds_baseline"] and h["around"]["lead_range_m"]["max_step"] > 5.0
  assert "ABOVE BASELINE" in rr.render(report)


def test_held_frames_and_their_age_are_reported_for_the_remote_backend_only():
  report = rr.analyze(drive(held_frames=2))
  remote, local = report["by_backend"]["jetlink"], report["by_backend"]["local"]
  assert remote["held_frames"] > 0 and remote["output_age_ms"]["max"] == 100.0
  assert local["held_frames"] == 0 and local["output_age_ms"]["n"] == 0


def test_a_disengagement_near_a_handover_is_attributed_to_it():
  report = rr.analyze(drive(disable=True))
  assert report["handovers"][0]["soft_disables"] == ["posenetInvalid"]


def test_the_radar_to_model_lag_is_reported():
  report = rr.analyze(drive())
  assert 1.5 < report["radar"]["md_lag_ms"]["p50"] < 2.5     # radarState is stamped 2 ms after the modelV2 it used


def test_a_drive_with_no_handover_reports_none():
  m = [x for x in drive() if x.which() != "starpilotModelV2"]
  report = rr.analyze(m)
  assert report["handovers"] == [] and set(report["by_backend"]) == {"local"}
