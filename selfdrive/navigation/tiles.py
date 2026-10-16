"""The basemap mapsd renders from.

comma's mapsd reads a hosted Protomaps basemap from comma's servers with a device token; this fork's devices are
registered with Konik. So the basemap is either a local Protomaps extract (e.g. `pmtiles extract <planet build>
basemap.pmtiles --bbox=...`) copied to BASEMAP_PATH, or else the offline OSM roads StarPilot's mapd already downloaded.
"""
import os
from pathlib import Path

from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths

from openpilot.selfdrive.navigation.pmtiles import PMTiles

BASEMAP_PATH = Path(Paths.comma_home() if PC else '/data/media/0') / 'navigation' / 'basemap.pmtiles'
OFFLINE_ROOT = Path('/data/media/0/osm/offline')  # StarPilot mapd's downloads


def basemap_available() -> bool:
  return BASEMAP_PATH.is_file() or (OFFLINE_ROOT.is_dir() and any(OFFLINE_ROOT.glob('*/*/*')))


def open_basemap():
  """A Protomaps extract when there is one, as in training; else mapd's offline roads."""
  if BASEMAP_PATH.is_file():
    return PMTiles(LocalTiles())
  from openpilot.selfdrive.navigation.mapd_tiles import MapdArchive
  return MapdArchive(OFFLINE_ROOT)


class LocalTiles:
  def __init__(self, path: Path | None = None):
    self.file = open(path or BASEMAP_PATH, 'rb')
    self.size = os.fstat(self.file.fileno()).st_size

  def read(self, offset: int, length: int) -> bytes:
    return os.pread(self.file.fileno(), length, offset)

  def prefetch(self, ranges):
    """Every range is already on disk."""

  def close(self):
    self.file.close()
