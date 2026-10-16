import gzip
import struct
import tempfile
import unittest  # noqa: TID251  comma's tests, kept as written
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch  # noqa: TID251

import numpy as np

import cereal.messaging as messaging
from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.navigation import tiles
from openpilot.selfdrive.navigation.mapd_tiles import SCHEMA, MapdArchive
from openpilot.selfdrive.navigation.mapsd import MapsD
from openpilot.selfdrive.navigation.pmtiles import PMTiles, decode_directory, tile_id
from openpilot.selfdrive.navigation.renderer import MAJOR, MEDIUM, MINOR, SIZE, STREET, TRACK, MapRenderer, draw_segments, mercator, project, road_style, \
  stroke_widths
from openpilot.selfdrive.navigation.route import RouteTracker
from openpilot.selfdrive.navigation.tiles import LocalTiles
from openpilot.selfdrive.navigation.vector_tile import decode_lines, decode_roads
from openpilot.starpilot.navigation import navigationd

# Ported from commaai/openpilot 4c362ca32 (nav alpha). The PMTiles, vector tile, rendering and route tracking tests are
# comma's, unchanged; the basemap is a local file here and the route comes from StarPilot's navigationd, not comma's navd.


METER = 1 / 111319.49079327358  # degrees of latitude


def draw_line(image, points, intensity, width, **kwargs):
  draw_segments(image, points[:-1], points[1:], width / 2, intensity, **kwargs)


def varint(value):
  output = bytearray()
  while value > 127:
    output.append((value & 127) | 128)
    value >>= 7
  output.append(value)
  return bytes(output)


def field(number, value):
  if isinstance(value, bytes):
    return varint(number << 3 | 2) + varint(len(value)) + value
  return varint(number << 3) + varint(value)


def road_tile(crossing=None):
  # One vertical line, from (2048, 0) to (2048, 4096), and one non-road layer. With crossing='bridge' or 'tunnel',
  # a horizontal line from (1024, 2048) to (3072, 2048) at that level.
  geometry = b''.join(varint(v) for v in [9, 4096, 0, 10, 0, 8192])
  feature = field(2, b'\x00\x00') + field(3, 2) + field(4, geometry)
  roads = field(15, 2) + field(1, b'roads') + field(2, feature)
  if crossing is not None:
    geometry = b''.join(varint(v) for v in [9, 2048, 4096, 10, 4096, 0])
    roads += field(2, field(2, b'\x00\x00\x01\x01') + field(3, 2) + field(4, geometry))
  roads += field(3, b'kind') + field(3, f'is_{crossing}'.encode()) + field(4, field(1, b'minor_road')) + field(4, field(7, 1)) + field(5, 4096)
  return field(3, field(1, b'buildings')) + field(3, roads)


def make_archive(payload=None, leaf=False, run=1, max_zoom=0):
  """A PMTiles archive with one zoom-zero tile, in the root directory or in a leaf directory."""
  tile = gzip.compress(road_tile() if payload is None else payload)
  directory = gzip.compress(varint(1) + varint(0) + varint(run) + varint(len(tile)) + varint(1))
  child = directory if leaf else b''
  root = gzip.compress(varint(1) + varint(0) + varint(0) + varint(len(child)) + varint(1)) if leaf else directory
  metadata = gzip.compress(b'{"vector_layers":[{"id":"roads"}]}')
  header = bytearray(127)
  header[:8] = b'PMTiles\x03'
  offsets = [127, 127 + len(root), 127 + len(root) + len(metadata), 127 + len(root) + len(metadata) + len(child)]
  struct.pack_into('<11Q', header, 8, offsets[0], len(root), offsets[1], len(metadata), offsets[2], len(child), offsets[3], len(tile), 1, 1, 1)
  header[96:102] = bytes([1, 2, 2, 1, 0, max_zoom])
  return bytes(header + root + metadata + child + tile)


@contextmanager
def local_archive(data):
  """A PMTiles reader over in-memory bytes, bypassing the tile server."""
  source = MagicMock(size=len(data))
  source.read.side_effect = lambda offset, length: data[offset:offset + length]
  with closing(PMTiles(source)) as archive:
    yield archive



class BasemapCase(unittest.TestCase):
  """A leaf-directory archive in a temporary file standing in for the device basemap."""

  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.basemap = Path(self.directory.name) / 'basemap.pmtiles'
    self.basemap.write_bytes(make_archive(leaf=True))
    self.enterContext(patch.object(tiles, 'BASEMAP_PATH', self.basemap))
    self.enterContext(patch.object(tiles, 'OFFLINE_ROOT', Path(self.directory.name) / 'osm' / 'offline'))  # none


class TestLocalTiles(BasemapCase):
  def test_reads_and_availability(self):
    with closing(PMTiles(LocalTiles(self.basemap))) as archive:
      self.assertEqual(gzip.decompress(archive.read(*archive.locate(0, 0, 0))), road_tile())
      self.assertIsNone(archive.locate(1, 0, 0))
    self.assertTrue(tiles.basemap_available())
    self.basemap.unlink()
    self.assertFalse(tiles.basemap_available())


def write_box(root, ways, bounds=(40.75, -82.0, 41.0, -81.75)):
  """A mapd offline box with ways of (highway class, id, [(longitude, latitude), ...])."""
  offline = SCHEMA.Offline.new_message(minLat=bounds[0], minLon=bounds[1], maxLat=bounds[2], maxLon=bounds[3], overlap=0.001)
  entries = offline.init('ways', len(ways))
  for entry, (highway_class, way_id, nodes) in zip(entries, ways, strict=True):
    entry.highwayClass, entry.id = highway_class, way_id
    (entry.minLon, entry.minLat), (entry.maxLon, entry.maxLat) = np.min(nodes, axis=0).tolist(), np.max(nodes, axis=0).tolist()
    for node, (lon, lat) in zip(entry.init('nodes', len(nodes)), nodes, strict=True):
      node.longitude, node.latitude = lon, lat
  path = root / str(int(bounds[0] // 2 * 2)) / str(int(bounds[1] // 2 * 2)) / '_'.join(f'{b:f}' for b in bounds)
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_bytes(offline.to_bytes_packed())


class TestMapdTiles(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.root = Path(self.directory.name)

  def test_roads_as_protomaps_tiles(self):
    lon, lat, m = -81.9, 40.85, 1 / 111319.49
    north_south = [(lon, lat - 300 * m), (lon, lat + 300 * m)]
    write_box(self.root, [('motorway', 1, north_south), ('secondaryLink', 2, [(lon - 50 * m, lat), (lon + 50 * m, lat)]),
                          ('residential', 3, [(lon + 2000 * m, lat), (lon + 2050 * m, lat)])])
    write_box(self.root, [('motorway', 1, north_south)], bounds=(40.75, -81.751, 41.0, -81.5))  # overlap: drawn once
    archive = MapdArchive(self.root)
    count = 1 << archive.max_zoom
    x, y = (mercator(np.array([[lon, lat]]))[0] * count).astype(int)
    roads = decode_roads(archive.get(archive.max_zoom, x, y))
    self.assertEqual(sorted((road.kind, road.detail) for road in roads), [('highway', 'motorway'), ('major_road', 'secondary_link')])
    self.assertEqual([road_style(road) for road in roads if road.detail == 'motorway'], [MAJOR])
    self.assertEqual([road_style(road) for road in roads if road.detail == 'secondary_link'], [MINOR])
    # clipped to the tile plus its buffer, in tile fractions
    for road in roads:
      self.assertTrue(((road.points > -0.05) & (road.points < 1.05)).all())
    self.assertIsNone(archive.get(archive.max_zoom, 0, 0))  # outside the downloaded area

    # the renderer draws the motorway under a route along it, with the ego on it
    image, valid = MapRenderer(archive).render(lon, lat, 0.0, np.array(north_south))
    self.assertTrue(valid)
    self.assertEqual((image[128, 128], image[128, 133], image[128, 145]), (128, 255, 0))  # a 16 m motorway stroke
    self.assertEqual((image[192, 100], image[192, 80]), (255, 0))  # the link across the ego, 38 m to each side here

  def test_open_basemap_prefers_protomaps(self):
    write_box(self.root / 'osm', [('residential', 1, [(-81.9, 40.85), (-81.9, 40.86)])])
    basemap = self.root / 'basemap.pmtiles'
    with patch.object(tiles, 'BASEMAP_PATH', basemap), patch.object(tiles, 'OFFLINE_ROOT', self.root / 'osm'):
      self.assertTrue(tiles.basemap_available())
      archive = tiles.open_basemap()
      self.assertIsInstance(archive, MapdArchive)
      archive.close()
      basemap.write_bytes(make_archive())
      archive = tiles.open_basemap()
      self.assertIsInstance(archive, PMTiles)
      archive.close()


class TestMapsD(BasemapCase):
  def test_nav_route_to_map_frames(self):
    """StarPilot's navRoute and a GPS fix over messaging; mapsd renders map frames from the local basemap."""
    with OpenpilotPrefix():
      pm = messaging.PubMaster(['navRoute', 'gpsLocationExternal'])
      sm = messaging.SubMaster(['gpsLocation', 'gpsLocationExternal', 'navRoute'])
      mapsd = MapsD()
      self.addCleanup(mapsd.close)

      def send_route(coordinates):
        msg = messaging.new_message('navRoute', valid=bool(coordinates))
        msg.navRoute.coordinates = [{'longitude': lon, 'latitude': lat} for lon, lat in coordinates]
        pm.send('navRoute', msg)

      def frame(fix=True):
        gps = messaging.new_message('gpsLocationExternal', valid=True)
        gps.gpsLocationExternal.hasFix = fix
        pm.send('gpsLocationExternal', gps)
        sm.update(0)
        return mapsd.update(sm)

      route = [(0, -0.01), (0, 0.01)]
      send_route(route)
      image, timestamp = frame()
      # The route is centered over the white road, with the ego arrow three quarters down.
      self.assertEqual((image[128, 128], image[128, 131], image[188, 128], image[195, 128]), (128, 255, 255, 0))
      self.assertEqual(timestamp, sm.logMonoTime['gpsLocationExternal'])
      tracker = mapsd.tracker
      send_route(route)  # navigationd's periodic resend of the same route
      frame()
      self.assertIs(mapsd.tracker, tracker)  # progress along it is kept
      send_route([])
      self.assertFalse(frame()[0].any())  # black without a route
      send_route(route)
      self.assertEqual(frame()[0][128, 128], 128)
      image, timestamp = frame(fix=False)
      self.assertFalse(image.any() or timestamp)  # black, not stale, without a fix

      # A missing basemap goes black, and a fresh reader is only tried again after a delay.
      mapsd.close()
      self.basemap.rename(self.basemap.with_suffix('.moved'))
      image, timestamp = frame()
      self.assertFalse(image.any() or timestamp)
      self.basemap.with_suffix('.moved').rename(self.basemap)
      self.assertFalse(frame()[1])
      mapsd.retry_at = 0
      self.assertEqual(frame()[0][128, 128], 128)


class TestNavigationdRouteResend(unittest.TestCase):
  def test_route_sent_on_change_and_periodically(self):
    with OpenpilotPrefix():
      nav = navigationd.Navigationd(route_engine=MagicMock())
    nav.pm = MagicMock()
    route = SimpleRoute([navigationd.Coordinate(0.0, 0.0), navigationd.Coordinate(0.01, 0.0)])
    nav._route, nav._route_generation = route, 1
    clock = [100.0]
    with patch.object(navigationd, 'monotonic', side_effect=lambda: clock[0]):
      nav._publish_nav_route_if_needed()
      self.assertEqual(nav.pm.send.call_count, 1)
      clock[0] += navigationd.ROUTE_RESEND_SECONDS - 1
      nav._publish_nav_route_if_needed()
      self.assertEqual(nav.pm.send.call_count, 1)
      clock[0] += 1
      nav._publish_nav_route_if_needed()
      self.assertEqual(nav.pm.send.call_count, 2)  # resent unchanged
      nav._route_generation = 2
      nav._publish_nav_route_if_needed()
      self.assertEqual(nav.pm.send.call_count, 3)  # sent at once on a new route
    sent = nav.pm.send.call_args.args[1]
    np.testing.assert_allclose([(c.latitude, c.longitude) for c in sent.navRoute.coordinates], [(0.0, 0.0), (0.01, 0.0)], atol=1e-7)


class SimpleRoute:
  def __init__(self, geometry):
    self.geometry = geometry


class TestTiles(unittest.TestCase):
  def test_pmtiles_format(self):
    self.assertEqual([tile_id(1, x, y) for x, y in [(0, 0), (0, 1), (1, 1), (1, 0)]], [1, 2, 3, 4])
    self.assertEqual(sorted(tile_id(3, x, y) for x in range(8) for y in range(8)), list(range(21, 85)))
    # IDs 5, 10; runs 3, 1; lengths 4, 6; the second offset follows the first blob.
    data = bytes([2, 5, 5, 3, 1, 4, 6, 1, 0])
    self.assertEqual(decode_directory(data), ([5, 10], [(3, 4, 0), (1, 6, 4)]))
    for invalid in (b'\x80', b'\x01\x00\x01\x01\x00', data + b'\x00'):
      with self.assertRaises(ValueError):
        decode_directory(invalid)
    with local_archive(make_archive(run=3, max_zoom=1)) as archive:  # the zoom-zero tile is also addressed by IDs 1 and 2
      self.assertEqual(archive.get(1, 0, 1), road_tile())
      self.assertIsNone(archive.get(1, 1, 1))
    with self.assertRaises(ValueError), local_archive(make_archive()[:-1]):
      pass

  def test_vector_tiles(self):
    roads = decode_roads(road_tile())
    self.assertEqual((len(roads), roads[0].kind), (1, 'minor_road'))
    np.testing.assert_array_equal(roads[0].points, [[0.5, 0], [0.5, 1]])
    lines = decode_lines([9, 20, 20, 10, 10, 0, 9, 9, 9, 10, 0, 10])
    np.testing.assert_array_equal(lines[0], [[10, 10], [15, 10]])
    np.testing.assert_array_equal(lines[1], [[10, 5], [10, 10]])
    for data in (b'\x1a\xff', b'\x00', b'\x1a\x02\x0a\x04'):
      with self.assertRaises(ValueError):
        decode_roads(data)
    for commands in ([10, 1, 1], [9, 0], [9, 0, 0, 15]):
      with self.assertRaises(ValueError):
        decode_lines(commands)


class TestRendering(unittest.TestCase):
  def test_projection(self):
    # At the equator, 64m ahead is the image center and the car is 64px below it, at 1m per pixel.
    points = mercator(np.array([[0, 0], [0, 64 * METER], [64 * METER, 0]]))
    np.testing.assert_allclose(project(points, 0, 0, 0), [[128, 192], [128, 128], [192, 192]], atol=1e-5)
    np.testing.assert_allclose(project(points, 0, 0, 90), [[128, 192], [64, 192], [128, 128]], atol=1e-5)
    pixels = project(mercator(np.array([[-179.999, 0]])), 179.999, 0, 90)  # across the antimeridian
    self.assertAlmostEqual(pixels[0, 1], 192 - 222.6389816, places=5)

  def test_strokes(self):
    image = np.zeros((SIZE, SIZE), dtype=np.uint8)
    draw_line(image, np.array([[-1000, 128], [1000, 128]]), 255, 8)
    self.assertTrue(np.all(image[128] == 255))
    draw_line(image, np.array([[128, 0], [128, 256]]), 128, 5, overlay=True)  # the grey route replaces the white road
    self.assertEqual((image[128, 128], image[128, 131]), (128, 255))
    before = image.copy()
    draw_line(image, np.array([[-1000, -1000], [-500, -500]]), 255, 5)
    np.testing.assert_array_equal(image, before)
    draw_line(image, np.array([[40, 40], [40, 40]]), 255, 5)  # a zero-length segment is still a dot
    self.assertEqual(image[40, 40], 255)

  def test_crossings(self):
    route = np.array([[0.01, 0], [0.01, 0.01]])  # off to the side, out of the way of the probes
    images = {}
    for crossing in ('bridge', 'tunnel'):
      with local_archive(make_archive(road_tile(crossing))) as archive:
        images[crossing] = MapRenderer(archive).render(0, -40 * METER, 0, route)[0]  # the crossing 40m ahead
    # The horizontal road crosses the vertical one 40px above the ego, at row 152. A bridge severs the road beneath
    # just outside its own stroke; a tunnel passes underneath untouched. The cut has butt caps, so the
    # bridge's own end is not wrapped in black.
    self.assertEqual((images['bridge'][146, 128], images['bridge'][152, 128], images['bridge'][152, 200], images['bridge'][140, 128]), (0, 255, 255, 255))
    self.assertEqual((images['tunnel'][146, 128], images['tunnel'][152, 200]), (255, 255))
    # The ground road cuts over the tunnel beneath it, and the tunnel is drawn without its casing.
    self.assertEqual((images['tunnel'][152, 133], images['tunnel'][147, 200]), (0, 0))

  def test_road_widths(self):
    # Pinned at the style zoom of 1 m per pixel: 16.26 at the equator and 15.26 at 60 degrees. Tunnels have no casing.
    styles, levels = np.array([MAJOR, MEDIUM, STREET, MINOR, TRACK, STREET]), np.array([0, 0, 0, 0, 0, -1])
    np.testing.assert_allclose(stroke_widths(16.256, styles, levels), [19.02, 15.48, 9.86, 6.70, 7.02, 7.89], atol=0.01)
    np.testing.assert_allclose(stroke_widths(15.256, styles, levels), [13.52, 10.78, 6.39, 4.16, 4.58, 4.62], atol=0.01)

  def test_route_tiles(self):
    route = np.array([[0, -0.01], [0, 0.01]])  # 2.2 km north along the prime meridian
    with local_archive(make_archive(max_zoom=15)) as archive:
      renderer = MapRenderer(archive)
      tiles = renderer.route_tiles(route)
      # Both columns beside the meridian, and the rows within the view radius of the route's ends.
      self.assertEqual({x for x, _ in tiles}, {16383, 16384})
      self.assertEqual({y for _, y in tiles}, set(range(16382, 16386)))

  def test_validity_and_display(self):
    route = np.array([[0, -0.01], [0, 0.01]])
    with local_archive(make_archive()) as archive:
      renderer = MapRenderer(archive)
      self.assertTrue(renderer.render(0, 0, 0, route)[1])
      self.assertFalse(renderer.render(0.01, 0, 0, route)[1])  # no road near the ego
      with patch.object(archive, 'get', return_value=None):  # a missing tile
        image, valid = MapRenderer(archive).render(0, 0, 0, route)
        self.assertFalse(valid)
        self.assertEqual(image[128, 128], 128)  # the route is still drawn
    with local_archive(make_archive(field(3, field(1, b'buildings')))) as archive:  # tiles without roads
      self.assertFalse(MapRenderer(archive).render(0, 0, 0, route)[1])


class TestRouteTracking(unittest.TestCase):
  def test_snap_heading_and_window(self):
    m = METER
    tracker = RouteTracker(np.array([[0, 0], [0, 200 * m], [200 * m, 200 * m]]))  # north 200m, then east 200m
    longitude, latitude, bearing = tracker.snap(3 * m, 100 * m)  # 3m right of the first leg
    self.assertAlmostEqual(tracker.progress, 100, delta=0.5)
    self.assertAlmostEqual(longitude, 0)  # lateral error removed
    self.assertAlmostEqual(latitude, 100 * m)
    self.assertAlmostEqual(bearing, 0, places=3)
    self.assertAlmostEqual(tracker.snap(0, 200 * m)[2], 45, places=2)  # at the corner the +-50m chord is mid-turn
    self.assertAlmostEqual(tracker.snap(0, 150 * m)[2], 45, places=2)  # progress never decreases
    tracker.snap(100 * m, 200 * m)  # progress 300: the window ahead no longer includes the first leg
    self.assertAlmostEqual(tracker.snap(150 * m, 200 * m)[0], 150 * m)  # so the window's offset is applied
    self.assertAlmostEqual(tracker.snap(200 * m, 200 * m)[2], 90, places=2)  # the chord clips at the route's end
    # Out and back along the same road: a fix near the far leg stays on the outbound leg within the window,
    # while a fresh tracker searches anywhere and lands on the return leg.
    route = np.array([[0, 0], [0, 1000 * m], [10 * m, 1000 * m], [10 * m, 0]])
    tracker = RouteTracker(route)
    tracker.snap(1 * m, 100 * m)
    self.assertAlmostEqual(tracker.snap(9 * m, 150 * m)[2], 0, places=3)
    self.assertAlmostEqual(tracker.progress, 150, delta=0.5)
    self.assertAlmostEqual(RouteTracker(route).snap(9 * m, 150 * m)[2], 180, places=3)


if __name__ == '__main__':
  unittest.main()
