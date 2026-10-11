"""LEAD_SWITCH (radard.py, D-106) and CAM_A_BOUND (D-105).

D-106: route 0000031b 14:34, both sensors switched from a lead at ~84 m onto a nearer, slower car. Both ranges fell
~20 m in about a second while each sensor's own speed explained far less, and the radar lead read as braking at -4.2.
SlideBound enters on that range mismatch and floors the lead at the camera's speed.

D-105: route 0000031b 14:57, the radar read a real lead slowing at -2.5 while the camera said -0.3. A confident camera
at the same range floors aLeadK at min(camera accel, 0) - CAM_A_BOUND_MARGIN."""
from types import SimpleNamespace

from openpilot.selfdrive.controls import radard

DT = 0.05  # modelV2 cadence
V_EGO = 17.5


def lead(v, d, trk=28, a=-1.0):
  return SimpleNamespace(status=True, radar=True, radarTrackId=trk, vLead=v, vLeadK=v, vRel=v - V_EGO, aLeadK=a, dRel=d)


def vis(v, x, prob=0.99, a=-0.3):
  return SimpleNamespace(v=[v], x=[x], prob=prob, a=[a])


def track(d, v_rel):
  return SimpleNamespace(dRel=d, vRel=v_rel)


def drive(sb, n, t0, cam_x, cam_v, rad_d, rad_vrel, lead_v, prob=0.99):
  """Feed n ticks; every argument after t0 is a function of tick index. Returns (fired list, last lead)."""
  fired, ld = [], None
  for i in range(n):
    ld = lead(lead_v(i), rad_d(i))
    fired.append(sb.step(ld, [], vis(cam_v(i), cam_x(i), prob), cam_v(i), t0 + i * DT, V_EGO, track(rad_d(i), rad_vrel(i))))
  return fired, ld


def follow(sb, n=40):
  # far lead at 80 m at our speed: ranges steady
  return drive(sb, n, 0.0, lambda i: 80.0, lambda i: 17.5, lambda i: 80.0, lambda i: 0.0, lambda i: 17.5)


def switch(sb, cam_drop=20.0, rad_drop=19.0, cam_v=17.5, lead_v=lambda i: 12.5, rad_vrel=-7.0, n=30):
  """A nearer car takes over: the camera steps cam_drop m in 0.5 s, the radar range slides rad_drop m over 1 s while
  U11 vRel says rad_vrel. Ticks start at t = 2 s."""
  def cam_x(i):
    return 80.0 - cam_drop * min(i / 10, 1.0)

  def rad_d(i):
    return 80.0 - rad_drop * min(i / 20, 1.0)
  return drive(sb, n, 40 * DT, cam_x, lambda i: cam_v, rad_d, lambda i: rad_vrel, lead_v)


def test_lead_switch_floors_lead_at_camera_speed():
  sb = radard.SlideBound()
  follow(sb)
  fired, ld = switch(sb)
  assert any(fired) and sb.switch_entries >= 1
  assert abs(ld.vLead - (17.5 - radard.SLIDE_MARGIN)) < 1e-6
  assert ld.aLeadK >= -0.3 - radard.SLIDE_A_MARGIN - 1e-6


def test_small_camera_step_does_not_fire():
  # 311 86:42, a real brake: camera excess peaked at -7.3 m, below the 10 m gate
  sb = radard.SlideBound()
  follow(sb)
  fired, _ = switch(sb, cam_drop=7.0)
  assert not any(fired) and sb.switch_entries == 0


def test_radar_range_explained_by_doppler_does_not_fire():
  # the radar range falls exactly as fast as its U11 vRel says: a real closing lead, not a switch
  sb = radard.SlideBound()
  follow(sb)
  fired, _ = switch(sb, rad_drop=12.0, rad_vrel=-12.0)
  assert not any(fired) and sb.switch_entries == 0


def test_camera_not_faster_than_lead_does_not_fire():
  # the camera sees the new car as slow as the radar does: nothing to floor
  sb = radard.SlideBound()
  follow(sb)
  fired, _ = switch(sb, cam_v=13.0, lead_v=lambda i: 12.0)
  assert not any(fired)


def test_unsure_camera_does_not_fire():
  sb = radard.SlideBound()
  follow(sb)
  fired, _ = drive(sb, 30, 40 * DT, lambda i: 80.0 - 20.0 * min(i / 10, 1.0), lambda i: 17.5,
                   lambda i: 80.0 - 19.0 * min(i / 20, 1.0), lambda i: -7.0, lambda i: 12.0, prob=0.6)
  assert not any(fired)


def test_lead_switch_disabled_does_not_fire(monkeypatch):
  monkeypatch.setattr(radard, "LEAD_SWITCH", False)
  sb = radard.SlideBound()
  follow(sb)
  fired, _ = switch(sb)
  assert not any(fired)



def cam_a_run(cab, n=25, d=35.0, cam_x=35.0, prob=0.99, cam_a=-0.3, a_lead=-2.5, others_fn=list):
  out = None
  for i in range(n):
    ld, ot = lead(14.0, d, a=a_lead), others_fn()
    out = (cab.step(ld, ot, vis(14.0, cam_x, prob, cam_a), i * DT), ld, ot)
  return out


def test_cam_a_bound_floors_radar_decel_at_camera():
  fired, ld, _ = cam_a_run(radard.CamABound())
  assert fired
  assert abs(ld.aLeadK - (-0.3 - radard.CAM_A_BOUND_MARGIN)) < 1e-6


def test_cam_a_bound_keeps_real_hard_brake():
  # 2f5 10:01: the camera saw -1.9, so a -2.5 radar reading stays (floor is -2.9)
  fired, ld, _ = cam_a_run(radard.CamABound(), cam_a=-1.9)
  assert not fired and ld.aLeadK == -2.5


def test_cam_a_bound_needs_confident_camera_at_same_range():
  assert not cam_a_run(radard.CamABound(), prob=0.6)[0]
  assert not cam_a_run(radard.CamABound(), cam_x=55.0)[0]
  assert not cam_a_run(radard.CamABound(), d=12.0, cam_x=12.0)[0]
  # under 1 s of camera history
  assert not cam_a_run(radard.CamABound(), n=5)[0]


def test_cam_a_bound_floors_same_track_in_other_slots_only():
  _, _, others = cam_a_run(radard.CamABound(), others_fn=lambda: [lead(14.0, 35.0, trk=28, a=-2.5),
                                                                   lead(14.0, 35.0, trk=9, a=-2.5)])
  assert abs(others[0].aLeadK - (-0.3 - radard.CAM_A_BOUND_MARGIN)) < 1e-6
  assert others[1].aLeadK == -2.5
