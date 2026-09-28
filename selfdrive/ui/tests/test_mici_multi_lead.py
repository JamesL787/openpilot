from types import SimpleNamespace

import pytest

from openpilot.selfdrive.ui.lib.starpilot_visuals import multi_lead_ui_enabled
from openpilot.selfdrive.ui.mici.onroad import model_renderer as mr
from openpilot.selfdrive.ui.mici.onroad.hud_renderer import ICBM_SET_SPEED_SCALE, combine_max_with_sign, icbm_ceiling_active, set_speed_scale


class FakeParams:
  def __init__(self, values):
    self.values = values

  def get_bool(self, key, block=False, default=False):
    return bool(self.values.get(key, default))


@pytest.mark.parametrize("developer_ui", [False, True])
@pytest.mark.parametrize("widgets", [False, True])
@pytest.mark.parametrize("adjacent", [False, True])
def test_multi_lead_ui_needs_all_three_toggles(developer_ui, widgets, adjacent):
  params = FakeParams({"DeveloperUI": developer_ui, "DeveloperWidgets": widgets, "AdjacentLeadsUI": adjacent})
  assert multi_lead_ui_enabled(params) is (developer_ui and widgets and adjacent)


@pytest.mark.parametrize("redneck, has_cp, op_long, expected", [
  (True, True, False, True),    # ICBM on a stock-ACC car
  (True, True, True, False),    # openpilot longitudinal: ICBM does not run
  (True, False, False, False),  # no CarParams yet
  (False, True, False, False),  # ICBM off
])
def test_icbm_ceiling_active(redneck, has_cp, op_long, expected):
  assert icbm_ceiling_active(redneck, has_cp, op_long) is expected


def _lead(status=True, v_lead=20.0):
  return SimpleNamespace(status=status, vLead=v_lead, dRel=30.0, yRel=0.0, vRel=0.0)


def _vehicle(x):
  return mr.LeadVehicle(glow=[(x, 0.0)] * 3, chevron=[(x + 10, 110.0), (x, 100.0), (x - 10, 110.0)], fill_alpha=0)


@pytest.fixture
def overlay(monkeypatch):
  renderer = object.__new__(mr.ModelRenderer)
  fans, labels = [], []
  monkeypatch.setattr(mr.rl, "draw_triangle_fan", lambda pts, n, color: fans.append(color))
  monkeypatch.setattr(mr.ui_state, "starpilot_toggles", {}, raising=False)
  monkeypatch.setattr(mr.ui_state, "is_metric", False, raising=False)
  renderer._draw_lead_label = lambda chevron, text, font_size=mr.LEAD_LABEL_FONT_SIZE, side=0: labels.append((chevron[1][0], text))
  return renderer, fans, labels


def test_overlay_labels_every_drawn_lead_and_draws_adjacent_markers(overlay):
  renderer, fans, labels = overlay
  renderer._lead_vehicles = [_vehicle(500), _vehicle(520)]
  renderer._adjacent_lead_vehicles = [_vehicle(200), _vehicle(800)]
  radar_state = SimpleNamespace(leadOne=_lead(v_lead=20.0), leadTwo=_lead(status=False))
  sp_radar = SimpleNamespace(leadLeft=_lead(v_lead=25.0), leadRight=_lead(v_lead=30.0))

  renderer._draw_multi_lead_overlay(radar_state, sp_radar)

  assert labels == [(500, "45 mph"), (200, "56 mph"), (800, "67 mph")]
  # glow + fill for each adjacent lead, in their own colours with a visible minimum alpha
  assert len(fans) == 4
  assert (fans[1].r, fans[1].g, fans[1].b) == (0, 150, 255)
  assert (fans[3].r, fans[3].g, fans[3].b) == (180, 0, 255)
  assert fans[1].a == mr.ADJACENT_LEAD_MIN_ALPHA


def test_overlay_without_adjacent_data_labels_only_in_lane_leads(overlay):
  renderer, fans, labels = overlay
  renderer._lead_vehicles = [_vehicle(500), mr.LeadVehicle()]
  renderer._adjacent_lead_vehicles = [mr.LeadVehicle(), mr.LeadVehicle()]
  radar_state = SimpleNamespace(leadOne=_lead(v_lead=10.0), leadTwo=_lead(v_lead=12.0))

  renderer._draw_multi_lead_overlay(radar_state, None)

  assert labels == [(500, "22 mph")]
  assert fans == []


@pytest.mark.parametrize("icbm, changed, expected", [
  (True, False, ICBM_SET_SPEED_SCALE),  # persistent ICBM ceiling: compact box
  (True, True, 1.0),                     # set speed just changed: stock pop-up size
  (False, True, 1.0),
  (False, False, 1.0),
])
def test_set_speed_scale(icbm, changed, expected):
  assert set_speed_scale(icbm, changed) == expected
  assert 0.4 < ICBM_SET_SPEED_SCALE < 0.7


@pytest.mark.parametrize("mode, multi, expected", [
  (mr.LeadInfoMode.SPEED, True, False),     # marker labels already show the lead speed
  (mr.LeadInfoMode.SPEED, False, True),
  (mr.LeadInfoMode.DISTANCE, True, True),   # distance is not on the marker labels
  (mr.LeadInfoMode.OFF, False, False),
  (mr.LeadInfoMode.OFF, True, False),
])
def test_show_top_lead_info(mode, multi, expected):
  assert mr.show_top_lead_info(mode, multi) is expected


@pytest.mark.parametrize("held, sign, changed, expected", [
  (True, True, False, True),    # persistent ICBM MAX folds into the speed-limit card
  (True, True, True, False),    # a set-speed change pops the stock box top-left
  (True, False, False, False),  # no sign: compact box stays top-left
  (False, True, False, False),  # no ICBM ceiling: plain sign
])
def test_combine_max_with_sign(held, sign, changed, expected):
  assert combine_max_with_sign(held, sign, changed) == expected


def test_adjacent_lead_marker_is_smaller():
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  rect = rl.Rectangle(0, 0, 1000, 500)
  full = r._update_lead_vehicle(30.0, 0.0, (500, 250), rect)
  side = r._update_lead_vehicle(30.0, 0.0, (500, 250), rect, scale=mr.ADJACENT_LEAD_SCALE)
  full_w = full.chevron[0][0] - full.chevron[2][0]
  side_w = side.chevron[0][0] - side.chevron[2][0]
  assert side_w == pytest.approx(full_w * mr.ADJACENT_LEAD_SCALE)
  assert mr.ADJACENT_LEAD_LABEL_FONT_SIZE < mr.LEAD_LABEL_FONT_SIZE


def _straight_lanes(ys=(-5.4, -1.8, 1.8, 5.4)):
  import numpy as np
  x = np.linspace(0.0, 100.0, 11, dtype=np.float32)
  return [np.stack([x, np.full_like(x, y), np.zeros_like(x)], axis=1) for y in ys]


@pytest.mark.parametrize("y_rel, left, probs, expected", [
  (3.6, True, (0.9, 0.9, 0.9, 0.9), True),     # centre of the left lane (model y == -yRel)
  (-3.6, False, (0.9, 0.9, 0.9, 0.9), True),   # centre of the right lane
  (9.0, True, (0.9, 0.9, 0.9, 0.9), False),    # two lanes over on the left
  (-9.0, False, (0.9, 0.9, 0.9, 0.9), False),  # two lanes over on the right
  (5.7, True, (0.9, 0.9, 0.9, 0.9), True),     # riding the far lane edge, inside the margin
  (-3.6, True, (0.9, 0.9, 0.9, 0.9), False),   # right-lane car is not a left lead
  (1.0, True, (0.9, 0.9, 0.9, 0.9), False),    # inside our own lane
  (5.0, True, (0.0, 0.9, 0.9, 0.9), True),     # far line untrusted: our lane width (3.6) + margin stands in
  (6.5, True, (0.0, 0.9, 0.9, 0.9), False),
])
def test_lead_in_adjacent_lane(y_rel, left, probs, expected):
  assert mr.lead_in_adjacent_lane(40.0, y_rel, left, _straight_lanes(), probs) is expected


def test_lead_in_adjacent_lane_needs_lane_lines_and_range():
  probs = (0.9, 0.9, 0.9, 0.9)
  assert not mr.lead_in_adjacent_lane(40.0, 3.6, True, [], probs)
  assert not mr.lead_in_adjacent_lane(150.0, 3.6, True, _straight_lanes(), probs)  # past the model's lane lines
  assert not mr.lead_in_adjacent_lane(-2.0, 3.6, True, _straight_lanes(), probs)


def _label_renderer(monkeypatch, obstacles=(), placed=()):
  """Bare renderer on a 400x240 view; every label measures 60x20, so its box is 66x22."""
  import pyray as rl
  import openpilot.selfdrive.ui.onroad.starpilot.path as path
  drawn = []
  monkeypatch.setattr(mr, "measure_text_cached", lambda font, text, size: SimpleNamespace(x=60.0, y=20.0))
  monkeypatch.setattr(mr.gui_app, "font", lambda *a, **k: None)
  monkeypatch.setattr(path, "_draw_text_with_outline", lambda text, x, y, font, size: drawn.append(x))
  renderer = mr.ModelRenderer.__new__(mr.ModelRenderer)
  renderer._rect = rl.Rectangle(0, 0, 400, 240)
  renderer._lead_label_rects = list(placed)
  renderer.set_side_label_obstacles(list(obstacles))
  return renderer, drawn


def _chevron(x, y=100.0):
  return [(x + 10, y + 8), (x, y), (x - 10, y + 8)]


def _sign():
  import pyray as rl
  return rl.Rectangle(300, 20, 100, 140)


def test_side_label_on_the_speed_limit_sign_is_dropped(monkeypatch):
  # Owner 2026-09-28: sliding it left of the sign put it beside the in-path label, where it read as that car's speed.
  renderer, drawn = _label_renderer(monkeypatch, obstacles=[_sign()])
  renderer._draw_lead_label(_chevron(330), "38 mph", 22, side=1)
  assert drawn == []
  assert renderer._lead_label_rects == []


def test_side_label_blocked_by_a_label_still_slides_outward(monkeypatch):
  import pyray as rl
  renderer, drawn = _label_renderer(monkeypatch, placed=[rl.Rectangle(90, 100, 60, 40)])
  renderer._draw_lead_label(_chevron(100), "12 mph", 22, side=-1)
  assert drawn == [27.0]  # box 24..90, left of the placed label


def test_in_path_label_slides_off_the_sign(monkeypatch):
  # box 297..363 on the 300..400 sign, centre left of the sign's: slides left of it
  renderer, drawn = _label_renderer(monkeypatch, obstacles=[_sign()])
  renderer._draw_lead_label(_chevron(330), "22 mph", 26, side=0)
  assert drawn == [237.0]


def test_in_path_label_on_the_right_of_the_sign_centre_slides_right(monkeypatch):
  import pyray as rl
  renderer, drawn = _label_renderer(monkeypatch, obstacles=[rl.Rectangle(200, 20, 100, 140)])
  renderer._draw_lead_label(_chevron(280), "22 mph", 26, side=0)
  assert drawn == [303.0]


def test_in_path_label_boxed_in_by_the_sign_is_still_drawn(monkeypatch):
  import pyray as rl
  # left of the sign is taken by a label and right of it is off-screen; below the sign is taken too
  placed = [rl.Rectangle(200, 100, 90, 40), rl.Rectangle(300, 165, 100, 30)]
  renderer, drawn = _label_renderer(monkeypatch, obstacles=[_sign()], placed=placed)
  renderer._draw_lead_label(_chevron(340), "22 mph", 26, side=0)
  assert drawn == [310.0]


def test_in_path_label_drops_below_the_sign_when_no_side_fits(monkeypatch):
  import pyray as rl
  renderer, drawn = _label_renderer(monkeypatch, obstacles=[_sign()], placed=[rl.Rectangle(200, 100, 90, 40)])
  renderer._draw_lead_label(_chevron(340), "22 mph", 26, side=0)
  assert drawn == [320.0]


def test_side_label_does_not_jump_inward_past_the_label_it_hit(monkeypatch):
  import pyray as rl
  # 28f seg 6 51.2 s: the right-lane label touched the in-path label and the sign blocked outward; it went left of
  # the in-path label and read as a second in-path speed
  renderer, drawn = _label_renderer(monkeypatch, obstacles=[_sign()], placed=[rl.Rectangle(150, 100, 90, 40)])
  renderer._draw_lead_label(_chevron(265), "38 mph", 22, side=1)
  assert drawn == []


def test_side_label_is_not_moved_under_the_sign(monkeypatch):
  import pyray as rl
  # boxed in by labels on the left and the sign on the right: dropped, not parked under the sign
  placed = [rl.Rectangle(200, 100, 90, 40), rl.Rectangle(100, 100, 100, 40)]
  renderer, drawn = _label_renderer(monkeypatch, obstacles=[_sign()], placed=placed)
  renderer._draw_lead_label(_chevron(260), "38 mph", 22, side=1)
  assert drawn == []


def test_label_blocked_only_by_other_labels_is_not_moved_under_the_sign(monkeypatch):
  import pyray as rl
  # left-side label boxed in by labels, nowhere near the sign: hidden as before
  placed = [rl.Rectangle(0, 100, 130, 40), rl.Rectangle(130, 100, 90, 40), rl.Rectangle(220, 100, 70, 40)]
  renderer, drawn = _label_renderer(monkeypatch, obstacles=[_sign()], placed=placed)
  renderer._draw_lead_label(_chevron(100), "12 mph", 22, side=-1)
  assert drawn == []


def test_side_label_without_obstacles_stays_under_its_marker(monkeypatch):
  renderer, drawn = _label_renderer(monkeypatch)
  renderer._draw_lead_label(_chevron(330), "38 mph", 22, side=1)
  assert drawn == [300.0]


def _winding(pts):
  (x0, y0), (x1, y1), (x2, y2) = pts
  return (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)


def test_far_lead_marker_stays_upright_under_the_lead():
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  lead = r._update_lead_vehicle(30.0, 0.0, (250, 150), rl.Rectangle(0, 0, 500, 240), top=(250, 110))
  assert not lead.flipped
  assert lead.chevron[1] == (250, 150)  # tip up, at the lead's bottom edge


def test_close_lead_marker_flips_onto_the_roof():
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  rect = rl.Rectangle(0, 0, 500, 240)
  upright = r._update_lead_vehicle(5.0, 0.0, (250, 150), rect)
  # bottom edge below the view (it would be clamped), roof at y 90
  lead = r._update_lead_vehicle(5.0, 0.0, (250, 300), rect, top=(250, 90))
  assert lead.flipped
  assert lead.chevron[1] == (250, 90)                       # tip on the roof
  assert lead.chevron[0][1] < 90 and lead.chevron[2][1] < 90  # pointing down
  assert _winding(lead.chevron) == pytest.approx(_winding(upright.chevron))  # same fan winding, so raylib draws it
  assert _winding(lead.glow) * _winding(upright.glow) > 0


def test_flipped_marker_without_a_bottom_point_still_draws():
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  lead = r._update_lead_vehicle(3.0, 0.0, None, rl.Rectangle(0, 0, 500, 240), top=(250, 120))
  assert lead.flipped and lead.chevron[1] == (250, 120)
  assert r._update_lead_vehicle(3.0, 0.0, None, rl.Rectangle(0, 0, 500, 240)).chevron == []


def test_flipped_marker_leaves_room_for_its_label_at_the_top():
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  lead = r._update_lead_vehicle(3.0, 0.0, (250, 400), rl.Rectangle(0, 0, 500, 240), top=(250, 5))
  sz = lead.chevron[1][1] - lead.chevron[0][1]
  assert lead.chevron[0][1] >= mr.LEAD_LABEL_ROOM
  assert sz > 0


def test_flip_has_hysteresis():
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  rect = rl.Rectangle(0, 0, 500, 240)
  sz = 750 / (3.0 / 3 + 30)  # marker size at d_rel 3 m, in-path
  fits = rect.height - sz - mr.LEAD_LABEL_ROOM  # lowest tip whose label still fits under it
  point = (250, fits - sz * 0.5)  # label fits, but inside the unflip band
  assert not r._update_lead_vehicle(3.0, 0.0, point, rect, top=(250, 100)).flipped
  assert r._update_lead_vehicle(3.0, 0.0, point, rect, top=(250, 100), was_flipped=True).flipped
  far = (250, fits - sz * 1.5)
  assert not r._update_lead_vehicle(3.0, 0.0, far, rect, top=(250, 100), was_flipped=True).flipped


def test_marker_flips_when_only_its_label_would_be_cut_off():
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  rect = rl.Rectangle(0, 0, 500, 240)
  sz = 750 / (10.9 / 3 + 30)
  # marker itself is on screen (not clamped), but the label under it would run past the bottom edge
  point = (250, rect.height - sz - mr.LEAD_LABEL_ROOM + 5)
  upright = r._update_lead_vehicle(10.9, 0.0, point, rect)
  assert upright.chevron[1][1] == point[1]
  assert r._update_lead_vehicle(10.9, 0.0, point, rect, top=(250, 100)).flipped


def test_flipped_marker_label_goes_on_top(monkeypatch):
  import openpilot.selfdrive.ui.onroad.starpilot.path as path
  ys = []
  renderer, drawn = _label_renderer(monkeypatch)
  monkeypatch.setattr(path, "_draw_text_with_outline", lambda text, x, y, font, size: ys.append((x, y)))
  flipped = [(320, 92), (330, 100), (340, 92)]  # tip down at y 100, base at 92
  renderer._draw_lead_label(flipped, "5 mph", 26, side=0)
  assert ys == [(300.0, 70.0)]  # 60x20 label, 2 px above the base
  assert renderer._lead_label_rects[-1].y + renderer._lead_label_rects[-1].height <= 92


def test_label_near_the_view_edge_is_kept_on_screen(monkeypatch):
  renderer, drawn = _label_renderer(monkeypatch)
  renderer._draw_lead_label(_chevron(395), "12 mph", 26, side=0)
  assert drawn == [400 - 60 - 3]


def _placer(t):
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  r._rect = rl.Rectangle(0, 0, 500, 240)
  r._clock = lambda: t[0]
  return r


CLOSE, FAR, ROOF = (250, 400), (250, 100), (250, 60)


def test_flip_back_is_held_for_the_minimum_time():
  t = [0.0]
  r = _placer(t)
  assert r._place_lead(("path", 0), 5.0, 0.0, CLOSE, ROOF).flipped
  t[0] = 0.5  # lead creeps away: geometry says upright, but the flip is only 0.5 s old
  assert r._place_lead(("path", 0), 12.0, 0.0, FAR, ROOF).flipped
  t[0] = 1.05
  assert not r._place_lead(("path", 0), 12.0, 0.0, FAR, ROOF).flipped
  t[0] = 1.5  # and the upright form is held too
  assert not r._place_lead(("path", 0), 5.0, 0.0, CLOSE, ROOF).flipped
  t[0] = 2.1
  assert r._place_lead(("path", 0), 5.0, 0.0, CLOSE, ROOF).flipped


def test_flip_state_survives_a_short_dropout_but_not_a_long_one():
  t = [0.0]
  r = _placer(t)
  sz = 750 / (8.0 / 3 + 30)
  band = (250, r._rect.height - sz - mr.LEAD_LABEL_ROOM - 0.5 * sz)  # inside the unflip hysteresis band
  assert r._place_lead(("path", 0), 8.0, 0.0, CLOSE, ROOF).flipped
  t[0] = 1.5
  assert r._place_lead(("path", 0), 8.0, 0.0, CLOSE, ROOF).flipped
  t[0] = 1.6  # 00000267 seg 10 625.0 s: the lead blinks out for a frame and returns inside the band
  assert r._place_lead(("path", 0), 8.0, 0.0, band, ROOF).flipped
  t[0] = 3.0  # gone for 1.4 s: starts fresh, upright
  assert not r._place_lead(("path", 0), 8.0, 0.0, band, ROOF).flipped


def test_held_form_that_cannot_be_drawn_gives_way():
  t = [0.0]
  r = _placer(t)
  assert r._place_lead(("path", 0), 5.0, 0.0, CLOSE, ROOF).flipped
  t[0] = 0.2  # roof no longer projects: draw it upright rather than not at all
  lead = r._place_lead(("path", 0), 12.0, 0.0, FAR, None)
  assert not lead.flipped and lead.chevron


def _ld(d, y, track=-1, v=10.0):
  return SimpleNamespace(status=True, dRel=d, yRel=y, vLead=v, vRel=0.0, radarTrackId=track)


@pytest.mark.parametrize("a, b, expected", [
  (_ld(7.9, -3.2, 41), _ld(7.9, -3.2, 41), True),     # 00000267 seg 16 38.2 s: leadOne and leadRight, track 41
  (_ld(7.9, -3.2, 41), _ld(9.5, -3.0, 41), True),     # same track, positions drifted apart
  (_ld(40.0, -0.2), _ld(40.8, 0.4), True),            # vision-only (track -1), same spot
  (_ld(54.9, 0.1, 28), _ld(102.8, 2.8, 44), False),   # seg 13 782.7 s: two cars at the same speed
  (_ld(10.3, 0.0, 48), _ld(28.2, -3.3, 41), False),   # seg 10 618.5 s
  (_ld(7.9, -3.2, 41), SimpleNamespace(status=False, dRel=7.9, yRel=-3.2, radarTrackId=41), False),
])
def test_same_lead(a, b, expected):
  assert mr.same_lead(a, b) is expected


def _radar_renderer(monkeypatch, enabled, points, valid=True):
  import numpy as np
  import pyray as rl
  dots = []
  monkeypatch.setattr(mr.rl, "draw_circle_v", lambda c, r, color: dots.append((round(c.x), round(c.y), r)))
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  r._params = SimpleNamespace(get_bool=lambda key, default=False: enabled if key == "RadarTracksUI" else default)
  r._rect = rl.Rectangle(0, 0, 500, 240)
  r._clip_region = rl.Rectangle(-500, -500, 1500, 1240)
  x = np.linspace(0.0, 100.0, 33)
  r._path = SimpleNamespace(raw_points=np.stack([x, np.zeros_like(x), np.zeros_like(x)], axis=1))
  r._path_offset_z = 1.2
  # pinhole: screen x = 250 + 200*y/d, screen y = 100 + 200*z/d
  r._car_space_transform = np.array([[250.0, 200.0, 0.0], [100.0, 0.0, 200.0], [1.0, 0.0, 0.0]])
  return r, _TracksSM(valid, points), dots


class _TracksSM:
  def __init__(self, valid, points):
    self.valid = {"liveTracks": valid}
    self._tracks = SimpleNamespace(points=points)

  def __getitem__(self, key):
    return self._tracks


def test_radar_points_drawn_as_dots_on_the_road(monkeypatch):
  pts = [SimpleNamespace(dRel=20.0, yRel=0.0), SimpleNamespace(dRel=40.0, yRel=-2.0)]
  r, sm, dots = _radar_renderer(monkeypatch, True, pts)
  r._draw_radar_points(sm)
  # outline then fill per point; yRel -2 (right) projects right of centre
  assert dots == [(250, 112, mr.RADAR_POINT_OUTLINE_RADIUS), (250, 112, mr.RADAR_POINT_RADIUS),
                  (260, 106, mr.RADAR_POINT_OUTLINE_RADIUS), (260, 106, mr.RADAR_POINT_RADIUS)]


@pytest.mark.parametrize("enabled, valid", [(False, True), (True, False)])
def test_radar_points_need_the_toggle_and_valid_tracks(monkeypatch, enabled, valid):
  r, sm, dots = _radar_renderer(monkeypatch, enabled, [SimpleNamespace(dRel=20.0, yRel=0.0)], valid)
  r._draw_radar_points(sm)
  assert dots == []


def test_lead_two_that_is_lead_one_again_is_not_drawn():
  import numpy as np
  import pyray as rl
  r = mr.ModelRenderer.__new__(mr.ModelRenderer)
  r._rect = rl.Rectangle(0, 0, 500, 240)
  x = np.linspace(0.0, 100.0, 33)
  r._path = SimpleNamespace(raw_points=np.stack([x, np.zeros_like(x), np.zeros_like(x)], axis=1))
  r._path_offset_z = 1.2
  r._map_to_screen = lambda d, y, z: (250.0, 100.0)
  r._clock = lambda: 0.0
  same = SimpleNamespace(leadOne=_ld(2.65, -2.04), leadTwo=_ld(2.38, -1.87))  # 0000028a seg 28 1694.8 s
  r._update_leads(same, x)
  assert r._lead_vehicles[0].chevron and not r._lead_vehicles[1].chevron
  apart = SimpleNamespace(leadOne=_ld(19.0, -0.3), leadTwo=_ld(12.4, -1.0, 7))
  r._update_leads(apart, x)
  assert r._lead_vehicles[0].chevron and r._lead_vehicles[1].chevron


def test_off_screen_radar_points_are_dropped_not_pinned_to_the_edge(monkeypatch):
  # yRel 30 (left) at 20 m projects to x 250 - 300 = -50: off the 500 px view
  r, sm, dots = _radar_renderer(monkeypatch, True, [SimpleNamespace(dRel=20.0, yRel=30.0), SimpleNamespace(dRel=20.0, yRel=0.0)])
  r._draw_radar_points(sm)
  assert [d[:2] for d in dots] == [(250, 112), (250, 112)]
