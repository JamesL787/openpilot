"""Compiled incumbent IDs/layout and wire regressions for the nested startup type."""
from importlib.resources import files
from pathlib import Path
import re

import capnp
import pytest
from openpilot.cereal import custom, CEREAL_PATH
from openpilot.starpilot.car.tesla.tests.schema_fixture import layout
from openpilot.starpilot.car.tesla.tests.test_radar_schema_evolution import populated, assert_occupied_equal

FIXTURE = Path(__file__).with_name('fixtures') / 'custom_before_preap_pedal.capnp'


@pytest.fixture
def historical():
  parser = capnp.SchemaParser()
  yield parser.load(str(FIXTURE), imports=[CEREAL_PATH, str(files('opendbc') / 'car')])


def compare_node(old, new):
  assert old.schema.node.id == new.schema.node.id
  kind = old.schema.node.which()
  assert kind == new.schema.node.which()
  if kind == 'struct':
    assert layout(old.schema) == layout(new.schema)
  elif kind == 'enum':
    assert old.schema.node.enum.to_dict() == new.schema.node.enum.to_dict()
  for child in old.schema.node.nestedNodes:
    compare_node(getattr(old, child.name), getattr(new, child.name))


def test_all_incumbent_custom_type_ids_fields_and_layouts_are_preserved(historical):
  for name in re.findall(r'^(?:struct|enum) (\w+)', FIXTURE.read_text(), re.MULTILINE):
    compare_node(getattr(historical, name), getattr(custom, name))
  # Startup capsules have no parent slots; published phone GPS@3 stays occupied.
  assert set(custom.StarPilotCarControl.schema.fields) == {
    'hudControl', 'steeringLimitInfo', 'navigation', 'phoneGps'}
  assert custom.StarPilotCarControl.PreapPedalStartup.schema.node.id not in {
    getattr(historical, name).schema.node.id for name in
    re.findall(r'^struct (\w+)', FIXTURE.read_text(), re.MULTILINE)}


def test_standalone_startup_does_not_modify_parent_and_old_relay_preserves_navigation(historical):
  parent = populated(custom.StarPilotCarControl)
  original = parent.to_bytes()
  capsule = custom.StarPilotCarControl.PreapPedalStartup.new_message(
    version=1, kind=5, carParamsSha256=bytes(range(32)), safetyModel=39,
    safetyParam=7, factor=1.25, zero=-0.5, pedalBus=2, sourceMonoTime=1234)
  with custom.StarPilotCarControl.PreapPedalStartup.from_bytes(capsule.to_bytes()) as recovered:
    assert recovered.to_dict() == capsule.to_dict()
  parent.clear_write_flag()
  assert parent.to_bytes() == original
  with historical.StarPilotCarControl.from_bytes(original) as old:
    assert_occupied_equal(parent, old)
    relayed = old.as_builder().to_bytes()
  with custom.StarPilotCarControl.from_bytes(relayed) as recovered:
    assert_occupied_equal(parent, recovered)


def test_old_gps_and_pedal_status_survive_current_reader_and_old_relay(historical):
  old = historical.StarPilotCarState.new_message(pedalMaxRegen=True, pedalLongActive=True,
    sourceCarStateMonoTime=123456, gps={'sourceMonoTime': 123456, 'latitude': 41.25,
      'longitude': -87.5, 'altitude': 180., 'speed': 20., 'bearingDeg': 90., 'hasFix': True,
      'unixTimestampMillis': 1700000000000, 'vNED': [1., 2., 3.]})
  with custom.StarPilotCarState.from_bytes(old.to_bytes()) as current:
    assert {name: current.to_dict()[name] for name in old.to_dict()} == old.to_dict()
    relayed = current.as_builder().to_bytes()
  with historical.StarPilotCarState.from_bytes(relayed) as recovered:
    assert recovered.to_dict() == old.to_dict()
