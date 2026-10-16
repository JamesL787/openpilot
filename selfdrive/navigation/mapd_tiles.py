"""The device's offline OSM roads (StarPilot mapd's downloads) served as the Protomaps vector tiles the renderer reads.

comma renders from a hosted Protomaps basemap. mapd already keeps the same OSM roads on the device for the selected
states/nations, as 0.25 degree capnp boxes, so this encodes each zoom-15 tile's roads as an MVT 'roads' layer with the
Protomaps kind/kind_detail properties and leaves comma's renderer untouched. What mapd does not download is drawn
differently from training: no service roads, driveways, parking aisles, alleys or tracks, and no bridge or tunnel
levels, so crossings never cut over each other.
"""
import re
from functools import lru_cache
from pathlib import Path

import capnp
import numpy as np

from openpilot.selfdrive.navigation.renderer import ZOOM, mercator

SCHEMA = capnp.load(str(Path(__file__).parent / 'mapd_offline.capnp'))
EXTENT = 4096
BUFFER = 64  # extent units kept around each tile, so strokes and caps near an edge are drawn by both tiles
BOX_NAME = re.compile(r'(-?\d+\.\d+)_(-?\d+\.\d+)_(-?\d+\.\d+)_(-?\d+\.\d+)')

# mapd's highway classes as Protomaps (kind, kind_detail); kind_detail is the OSM highway type
CLASSES = {
  'motorway': ('highway', 'motorway'), 'motorwayLink': ('highway', 'motorway_link'),
  'trunk': ('major_road', 'trunk'), 'trunkLink': ('major_road', 'trunk_link'),
  'primary': ('major_road', 'primary'), 'primaryLink': ('major_road', 'primary_link'),
  'secondary': ('major_road', 'secondary'), 'secondaryLink': ('major_road', 'secondary_link'),
  'tertiary': ('major_road', 'tertiary'), 'tertiaryLink': ('major_road', 'tertiary_link'),
  'unclassified': ('minor_road', 'unclassified'), 'residential': ('minor_road', 'residential'),
  'livingStreet': ('other', 'living_street'), 'unknown': ('minor_road', ''),
}


def varint(value: int) -> bytes:
  output = bytearray()
  while value > 127:
    output.append((value & 127) | 128)
    value >>= 7
  output.append(value)
  return bytes(output)


def field(number: int, value: bytes | int) -> bytes:
  if isinstance(value, bytes):
    return varint(number << 3 | 2) + varint(len(value)) + value
  return varint(number << 3) + varint(value)


def packed(values) -> bytes:
  return b''.join(varint(v) for v in values)


def zigzag(value: int) -> int:
  return (value << 1) ^ (value >> 63)


def line_geometry(points: np.ndarray) -> list[int]:
  """MVT commands for one line of integer tile coordinates: MoveTo the first point, LineTo the rest."""
  deltas = np.diff(points, axis=0, prepend=np.zeros((1, 2), dtype=points.dtype))
  commands = [9, zigzag(int(deltas[0, 0])), zigzag(int(deltas[0, 1])), (len(points) - 1) << 3 | 2]
  for dx, dy in deltas[1:].tolist():
    commands += [zigzag(dx), zigzag(dy)]
  return commands


class MapdArchive:
  """The archive interface MapRenderer uses (zoom range, get, prefetch, close) over mapd's offline boxes."""
  min_zoom = max_zoom = ZOOM

  def __init__(self, root: Path):
    self.boxes = []  # (min_lat, min_lon, max_lat, max_lon, path)
    for path in root.glob('*/*/*'):
      match = BOX_NAME.fullmatch(path.name)
      if match is not None:
        self.boxes.append((*map(float, match.groups()), path))
    if not self.boxes:
      raise FileNotFoundError(f'No mapd offline data in {root}')
    self.load = lru_cache(maxsize=8)(self._load)

  def _load(self, path: Path):
    """A box's ways and their mercator bounds (x west, y north, x east, y south); points are converted on first use."""
    with open(path, 'rb') as f:
      offline = SCHEMA.Offline.from_bytes_packed(f.read(), traversal_limit_in_words=2**40)
    ways = list(offline.ways)
    corners = np.array([(way.minLon, way.maxLat, way.maxLon, way.minLat) for way in ways], dtype=np.float64).reshape(-1, 4)
    return ways, np.column_stack((mercator(corners[:, :2]), mercator(corners[:, 2:]))), {}

  def get(self, z: int, x: int, y: int) -> bytes | None:
    """The tile as an uncompressed MVT with one 'roads' layer, or None outside the downloaded area."""
    count = 1 << z
    (west, north), (east, south) = (x / count, y / count), ((x + 1) / count, (y + 1) / count)
    lon_west, lon_east = west * 360 - 180, east * 360 - 180
    lat_north, lat_south = (float(np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * v))))) for v in (north, south))
    boxes = [box for box in self.boxes if box[0] <= lat_north and lat_south <= box[2] and box[1] <= lon_east and lon_west <= box[3]]
    if not boxes:
      return None
    margin = BUFFER / EXTENT / count
    low, high = np.array([west - margin, north - margin]), np.array([east + margin, south + margin])
    values, features, seen = {}, [], set()
    for box in boxes:
      ways, bounds, converted = self.load(box[4])
      for i in np.flatnonzero((bounds[:, 0] <= high[0]) & (bounds[:, 2] >= low[0]) & (bounds[:, 1] <= high[1]) & (bounds[:, 3] >= low[1])):
        way = ways[i]
        if way.id in seen:  # neighboring boxes overlap
          continue
        seen.add(way.id)
        if i not in converted:
          converted[i] = mercator(np.array([(node.longitude, node.latitude) for node in way.nodes], dtype=np.float64).reshape(-1, 2))
        points = converted[i]
        if len(points) < 2:
          continue
        kind, detail = CLASSES.get(str(way.highwayClass), CLASSES['unknown'])
        # keep the segments touching the buffered tile, as runs of consecutive segments
        starts, ends = points[:-1], points[1:]
        touching = ((np.minimum(starts, ends) <= high) & (np.maximum(starts, ends) >= low)).all(axis=1)
        local = np.round((points * count - (x, y)) * EXTENT).astype(np.int64)
        edges = np.flatnonzero(np.diff(np.r_[0, touching.astype(np.int8), 0]))
        tags = packed([0, values.setdefault(kind, len(values)), 1, values.setdefault(detail, len(values))])
        for first, last in zip(edges[::2], edges[1::2], strict=True):
          line = local[first:last + 1]
          line = line[np.r_[True, (np.diff(line, axis=0) != 0).any(axis=1)]]  # drop repeats rounding made
          if len(line) >= 2:
            features.append(field(2, tags) + field(3, 2) + field(4, packed(line_geometry(line))))
    layer = (field(15, 2) + field(1, b'roads') + b''.join(field(2, feature) for feature in features) +
             field(3, b'kind') + field(3, b'kind_detail') +
             b''.join(field(4, field(1, value.encode())) for value in sorted(values, key=values.get)) + field(5, EXTENT))
    return field(3, layer)

  def prefetch(self, tiles):
    """Every box is already on disk."""

  def close(self):
    self.load.cache_clear()
