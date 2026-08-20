import itertools
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pygame

from matplotlib.backends.backend_agg import FigureCanvasAgg



RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

class UIParams:
  lidar_x, lidar_y, lidar_zoom = 384, 960, 6
  lidar_car_x, lidar_car_y = lidar_x / 2., lidar_y / 1.1
  car_hwidth = 1.7272 / 2 * lidar_zoom
  car_front = 2.6924 * lidar_zoom
  car_back = 1.8796 * lidar_zoom
  car_color = 110
UP = UIParams

METER_WIDTH = 20

class Calibration:
  def __init__(self, num_px, rpy, intrinsic, calib_scale):
    # Keep the replay radar-only path usable on a host without the optional
    # native transformation extension. Camera calibration is only needed when
    # a VisionIPC frame is actually available.
    from openpilot.common.transformations.camera import get_view_frame_from_calib_frame

    self.intrinsic = intrinsic
    self.extrinsics_matrix = get_view_frame_from_calib_frame(rpy[0], rpy[1], rpy[2], 0.0)[:,:3]
    self.zoom = calib_scale

  def car_space_to_ff(self, x, y, z):
    car_space_projective = np.column_stack((x, y, z)).T

    ep = self.extrinsics_matrix.dot(car_space_projective)
    kep = self.intrinsic.dot(ep)
    return (kep[:-1, :] / kep[-1, :]).T

  def car_space_to_bb(self, x, y, z):
    pts = self.car_space_to_ff(x, y, z)
    return pts / self.zoom


_COLOR_CACHE : dict[tuple[int, int, int], Any] = {}
def find_color(lidar_surface, color):
  if color in _COLOR_CACHE:
    return _COLOR_CACHE[color]
  tcolor = 0
  ret = 255
  for x in lidar_surface.get_palette():
    if x[0:3] == color:
      ret = tcolor
      break
    tcolor += 1
  _COLOR_CACHE[color] = ret
  return ret


def to_topdown_pt(y, x):
  px, py = x * UP.lidar_zoom + UP.lidar_car_x, -y * UP.lidar_zoom + UP.lidar_car_y
  if px > 0 and py > 0 and px < UP.lidar_x and py < UP.lidar_y:
    return int(px), int(py)
  return -1, -1


def draw_path(path, color, img, calibration, top_down, lid_color=None, z_off=0):
  x, y, z = np.asarray(path.x), np.asarray(path.y), np.asarray(path.z) + z_off
  pts = calibration.car_space_to_bb(x, y, z)
  pts = np.round(pts).astype(int)

  # draw lidar path point on lidar
  # find color in 8 bit
  if lid_color is not None and top_down is not None:
    tcolor = find_color(top_down[0], lid_color)
    for i in range(len(x)):
      px, py = to_topdown_pt(x[i], y[i])
      if px != -1:
        top_down[1][px, py] = tcolor

  height, width = img.shape[:2]
  for x, y in pts:
    if 1 < x < width - 1 and 1 < y < height - 1:
      for a, b in itertools.permutations([-1, 0, -1], 2):
        img[y + a, x + b] = color


def init_plots(arr, name_to_arr_idx, plot_xlims, plot_ylims, plot_names, plot_colors, plot_styles):
  color_palette = { "r": (1, 0, 0),
                    "g": (0, 1, 0),
                    "b": (0, 0, 1),
                    "k": (0, 0, 0),
                    "y": (1, 1, 0),
                    "p": (0, 1, 1),
                    "m": (1, 0, 1)}

  dpi = 90
  fig = plt.figure(figsize=(575 / dpi, 600 / dpi), dpi=dpi)
  canvas = FigureCanvasAgg(fig)

  fig.set_facecolor((0.2, 0.2, 0.2))
  fig.subplots_adjust(left=0.075, right=0.995, top=0.975, bottom=0.035, hspace=0.16)

  # Keep the plot headers readable inside the fixed-width replay panel.  The
  # full signal names are still present in the source/plot data; these compact
  # labels prevent the header from running off-screen on smaller displays.
  title_aliases = {
    "gas": "gas",
    "computer_gas": "cg",
    "user_brake": "ub",
    "computer_brake": "cb",
    "angle_steers": "steer",
    "angle_steers_des": "des",
    "angle_steers_k": "k",
    "steer_torque": "tq",
    "v_ego": "v",
    "v_override": "ovrd",
    "v_pid": "pid",
    "v_cruise": "cruise",
    "a_ego": "a",
    "a_target": "tgt",
  }

  axs = []
  for pn in range(len(plot_ylims)):
    ax = fig.add_subplot(len(plot_ylims), 1, len(axs)+1)
    ax.set_xlim(plot_xlims[pn][0], plot_xlims[pn][1])
    ax.set_ylim(plot_ylims[pn][0], plot_ylims[pn][1])
    ax.patch.set_facecolor((0.4, 0.4, 0.4))
    axs.append(ax)

  plots, idxs, plot_select = [], [], []
  for i, pl_list in enumerate(plot_names):
    for j, item in enumerate(pl_list):
      plot, = axs[i].plot(arr[:, name_to_arr_idx[item]],
                          label=item,
                          color=color_palette[plot_colors[i][j]],
                          linestyle=plot_styles[i][j])
      plots.append(plot)
      idxs.append(name_to_arr_idx[item])
      plot_select.append(i)
    title = " ".join(f"{title_aliases.get(nm, nm)}[{cl}]"
                      for (nm, cl) in zip(pl_list, plot_colors[i], strict=False))
    axs[i].set_title(title, loc="left", fontsize=7, pad=1, color="white")
    axs[i].tick_params(axis="x", colors="white", labelsize=7, pad=1)
    axs[i].tick_params(axis="y", colors="white", labelsize=7, pad=1)
    axs[i].title.set_color("white")

    if i < len(plot_ylims) - 1:
      axs[i].set_xticks([])

  canvas.draw()

  def draw_plots(arr):
    for ax in axs:
      ax.draw_artist(ax.patch)
    for i in range(len(plots)):
      plots[i].set_ydata(arr[:, idxs[i]])
      axs[plot_select[i]].draw_artist(plots[i])

    raw_data = canvas.buffer_rgba()
    plot_surface = pygame.image.frombuffer(raw_data, canvas.get_width_height(), "RGBA").convert()
    return plot_surface

  return draw_plots


def pygame_modules_have_loaded():
  return pygame.display.get_init() and pygame.font.get_init()


def plot_model(m, img, calibration, top_down):
  if calibration is None or top_down is None:
    return

  # Importing radard pulls in the host's native transformation extension. The
  # replay inspector can run from rlogs without that extension, so defer this
  # camera-only constant until model projection is actually requested.
  from openpilot.selfdrive.controls.radard import RADAR_TO_CAMERA

  for lead in m.leadsV3:
    if lead.prob < 0.5:
      continue

    x, y = lead.x[0], lead.y[0]
    x_std = lead.xStd[0]
    x -= RADAR_TO_CAMERA

    _, py_top = to_topdown_pt(x + x_std, y)
    px, py_bottom = to_topdown_pt(x - x_std, y)
    top_down[1][int(round(px - 4)):int(round(px + 4)), py_top:py_bottom] = find_color(top_down[0], YELLOW)

  for path, prob, _ in zip(m.laneLines, m.laneLineProbs, m.laneLineStds, strict=True):
    color = (0, int(255 * prob), 0)
    draw_path(path, color, img, calibration, top_down, YELLOW)

  for edge, std in zip(m.roadEdges, m.roadEdgeStds, strict=True):
    prob = max(1 - std, 0)
    color = (int(255 * prob), 0, 0)
    draw_path(edge, color, img, calibration, top_down, RED)

  color = (255, 0, 0)
  draw_path(m.position, color, img, calibration, top_down, RED, 1.22)


def plot_lead(rs, top_down):
  for lead in [rs.leadOne, rs.leadTwo]:
    if not lead.status:
      continue

    x = lead.dRel
    px_left, py = to_topdown_pt(x, -10)
    px_right, _ = to_topdown_pt(x, 10)
    top_down[1][px_left:px_right, py] = find_color(top_down[0], RED)


def maybe_update_radar_points(lt, lid_overlay, roles=None):
  """Draw radar points and return screen-space metadata for optional labels.

  ``trackId`` is the native persistent identity for the Bosch-A parser.  The
  optional role map is supplied by the replay inspector and never affects
  control or radar publication.
  """
  from openpilot.tools.replay.lib.radar_debug import radar_track_style

  points = []
  for track in lt or ():
    try:
      track_id = int(track.trackId)
    except (AttributeError, TypeError, ValueError):
      track_id = -1
    measured = bool(getattr(track, "measured", False))
    d_rel = float(getattr(track, "dRel", float("nan")))
    y_rel = float(getattr(track, "yRel", float("nan")))
    v_rel = float(getattr(track, "vRel", float("nan")))

    # negative here since radar is left positive
    px, py = to_topdown_pt(d_rel, -y_rel)
    if px == -1:
      continue

    role, palette_index = radar_track_style(track_id, measured, roles)
    lid_overlay[px - 4:px + 4, py - 4:py + 4] = palette_index
    lid_overlay[px - 2:px + 2, py - 2:py + 2] = palette_index
    points.append({
      "track_id": track_id,
      "d_rel": d_rel,
      "y_rel": y_rel,
      "v_rel": v_rel,
      "role": role,
      "x": px,
      "y": py,
    })
  return points

def get_blank_lid_overlay(UP):
  lid_overlay = np.zeros((UP.lidar_x, UP.lidar_y), 'uint8')
  # Draw the car.
  lid_overlay[int(round(UP.lidar_car_x - UP.car_hwidth)):int(
    round(UP.lidar_car_x + UP.car_hwidth)), int(round(UP.lidar_car_y -
                                                      UP.car_front))] = UP.car_color
  lid_overlay[int(round(UP.lidar_car_x - UP.car_hwidth)):int(
    round(UP.lidar_car_x + UP.car_hwidth)), int(round(UP.lidar_car_y +
                                                      UP.car_back))] = UP.car_color
  lid_overlay[int(round(UP.lidar_car_x - UP.car_hwidth)), int(
    round(UP.lidar_car_y - UP.car_front)):int(round(
      UP.lidar_car_y + UP.car_back))] = UP.car_color
  lid_overlay[int(round(UP.lidar_car_x + UP.car_hwidth)), int(
    round(UP.lidar_car_y - UP.car_front)):int(round(
      UP.lidar_car_y + UP.car_back))] = UP.car_color
  return lid_overlay
