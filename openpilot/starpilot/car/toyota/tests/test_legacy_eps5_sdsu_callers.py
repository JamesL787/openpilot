import pytest
from opendbc.car.toyota.values import CAR
from openpilot.starpilot.car.toyota.tests import test_rav4h_caller_native as helpers

from openpilot.starpilot.car.toyota.tests.test_toyota_cpp_transport import host_heartbeat_bridge as host_heartbeat_bridge

source_matched_native=helpers.source_matched_native
daemon_gc_scope=helpers.daemon_gc_scope
MODELS=(CAR.TOYOTA_HIGHLANDER,CAR.TOYOTA_SIENNA,CAR.LEXUS_NX,CAR.LEXUS_RX)


@pytest.mark.parametrize('candidate',MODELS)
@pytest.mark.parametrize('stock',[False,True])
@pytest.mark.parametrize('scenario',['physical','faults','bad_dlc','off'])
def test_legacy_sdsu_real_callers(candidate,stock,scenario,host_heartbeat_bridge):
  helpers.run_case(stock,scenario,candidate=candidate,bridge=host_heartbeat_bridge,input_clock=True)


@pytest.mark.parametrize('candidate',MODELS)
@pytest.mark.parametrize('stock',[False,True])
def test_legacy_sdsu_ordinary_cruise_without_aol(candidate,stock,host_heartbeat_bridge):
  helpers.run_case(stock,candidate=candidate,aol=False,bridge=host_heartbeat_bridge,input_clock=True)


@pytest.mark.parametrize('stock',[False,True])
def test_highlander_cold_low_speed_lateral_without_long(stock,host_heartbeat_bridge):
  helpers.run_case(stock,'cold_low',candidate=CAR.TOYOTA_HIGHLANDER,bridge=host_heartbeat_bridge,input_clock=True)
