"""Dom-compatible opt-in cluster display, independent of lateral authority."""
from openpilot.starpilot.saved_source import read_saved

KEY = "FordHandsFreeCluster"
CHOICES = {0: "Off", 1: "On"}


def qualified(cp):
  """Dom's CAN-FD/non-LKA scope, constrained to existing admitted owners."""
  from opendbc.car.ford.values import FordFlags
  from opendbc.car.ford.mache_lateral import qualified as mache
  from opendbc.car.ford.generic_canfd_lateral import qualified as generic
  from opendbc.car.ford.new_port_curvature import qualified as new_port
  from opendbc.bluepilot_lateral.hosts.starpilot import qualified as angle
  return bool(cp.brand == "ford" and cp.flags & FordFlags.CANFD and not cp.flags & FordFlags.LKA_STEERING and
              (mache(cp) or generic(cp) or new_port(cp) or angle(cp)))


def read_choice(params):
  raw, readable = read_saved(params, KEY, 8)
  valid = readable and raw in (None, b"0", b"1")
  return int(valid and raw == b"1"), raw, readable, valid


class FordClusterPreference:
  def __init__(self, params):
    self.params = params
    self.enabled = bool(read_choice(params)[0])
    self.frames = 0

  def update(self):
    if self.frames % 100 == 0:
      self.enabled = bool(read_choice(self.params)[0])
    self.frames += 1
