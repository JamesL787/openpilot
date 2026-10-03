"""radard's three newborn switches are built in off and follow set_bosch_a_newborn_leads() together."""
import ast
import inspect

import pytest

from openpilot.selfdrive.controls import radard

SWITCHES = ("NEWBORN_RANGE_CLOSING_EXEMPT", "NEWBORN_KF_FOLLOW_RANGE", "NEWBORN_LEAD_NEEDS_CLOSING")


@pytest.fixture(autouse=True)
def restore_off():
  yield
  radard.set_bosch_a_newborn_leads(False)


def test_source_defaults_are_off():
  tree = ast.parse(inspect.getsource(radard))
  defaults = {node.targets[0].id: node.value.value for node in tree.body
              if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in SWITCHES}
  assert defaults == dict.fromkeys(SWITCHES, False)


def test_setter_flips_all_three():
  radard.set_bosch_a_newborn_leads(True)
  assert all(getattr(radard, name) is True for name in SWITCHES)
  radard.set_bosch_a_newborn_leads(False)
  assert all(getattr(radard, name) is False for name in SWITCHES)


def test_off_closing_exemption_is_inert():
  radard.set_bosch_a_newborn_leads(False)
  assert not radard.young_range_genuinely_closing(object(), 19.8)
