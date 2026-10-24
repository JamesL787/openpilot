"""Combined angle authority retains the existing physical AOL lifecycle."""
import unittest
from opendbc.safety.tests import test_ford_aol as existing
from opendbc.bluepilot_lateral.core.angle import Command
from opendbc.bluepilot_lateral.can.ford import lateral, lka
from opendbc.safety.tests.libsafety import libsafety_py

class TestFordBluePilotAol(unittest.TestCase):
  setUp = existing.TestFordAolDriverIntent.setUp
  tearDown = existing.TestFordAolDriverIntent.tearDown
  reset = existing.TestFordAolDriverIntent.reset
  rx = existing.TestFordAolDriverIntent.rx
  pump = existing.TestFordAolDriverIntent.pump
  arm = existing.TestFordAolDriverIntent.arm
  rearm = existing.TestFordAolDriverIntent.rearm
  test_permanent_eps_then_clean_in_same_batch_revokes = existing.TestFordAolDriverIntent.test_permanent_eps_then_clean_in_same_batch_revokes
  test_reverse_temporary_eps_retain_but_heartbeat_loss_rearms = (
    existing.TestFordAolDriverIntent.test_reverse_temporary_eps_retain_but_heartbeat_loss_rearms)
  BASE_PROFILES = (146,147,160,161,194,195)
  PROFILES = BASE_PROFILES + tuple(word|256 for word in BASE_PROFILES)

  def test_nonzero_angle_after_brake_requires_fresh_shadow_and_native_lat(self):
    for word in self.PROFILES:
      self.reset(word)
      self.arm()
      assert not self.safety.get_controls_allowed()
      command = Command(True,0.005,0.005/10.)
      def send(frame):
        addr,data,bus=frame
        return bool(self.safety.safety_tx_hook(libsafety_py.make_CANPacket(addr,bus,data)))
      assert send(lka(self.packer,0,command.shadow_curvature,0))
      assert send(lateral(self.packer,0,command,canfd=bool(word&2),counter=0))
      self.rx('EngBrakeData',{'BpedDrvAppl_D_Actl':2,'CcStat_D_Actl':3})
      self.pump(5,mask=1)
      assert self.safety.aol_get_permission_mask()==1 and not self.safety.get_controls_allowed()
      assert send(lka(self.packer,0,command.shadow_curvature,1))
      assert send(lateral(self.packer,0,command,canfd=bool(word&2),counter=1))
      self.pump(10,mask=1)
      assert self.safety.aol_get_permission_mask()==1 and not self.safety.get_controls_allowed()
      assert send(lka(self.packer,0,command.shadow_curvature,2))
      assert send(lateral(self.packer,0,command,canfd=bool(word&2),counter=2))
      self.safety.aol_set_host_request(0)
      self.pump(5,mask=0)
      assert not send(lateral(self.packer,0,command,canfd=bool(word&2),counter=2))
