"""Actual Ford factory, parser, Card, SelfdriveD, Controls and native matrix.

CAN, perception, USB and clocks are synthetic; no physical acceptance claim.
"""
import pytest
from openpilot.starpilot.tests.ford_lifecycle_helpers import FORD_FACTORIES, ford_joined as ford_joined, run_actual_producer


@pytest.fixture(autouse=True)
def configuration_topology(monkeypatch, topology):
  monkeypatch.ford_topology = topology


@pytest.mark.parametrize('identity', FORD_FACTORIES)
@pytest.mark.parametrize('alpha', [False, True])
@pytest.mark.parametrize('hands_free', [False])
@pytest.mark.parametrize('topology', ['automatic', 'manual', 'multi-panda', 'manual-multi'])
def test_actual_configuration_lifecycle(ford_joined, monkeypatch):
  run_actual_producer(ford_joined, monkeypatch, scenario='configuration-parity')
