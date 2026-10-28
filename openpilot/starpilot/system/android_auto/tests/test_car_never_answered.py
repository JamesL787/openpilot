import errno
import unittest

from openpilot.starpilot.system.android_auto.bootstrap import BootstrapTimeout
from openpilot.starpilot.system.android_auto.supervisor import car_never_answered


class TestCarNeverAnswered(unittest.TestCase):
  def test_local_bluetooth_failures_keep_the_cached_channel(self):
    for code in (errno.ENOSYS, errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT):
      self.assertFalse(car_never_answered(OSError(code, 'local')))

  def test_car_side_failures_drop_the_cached_channel(self):
    for error in (OSError(errno.ECONNREFUSED, 'refused'), OSError(errno.EHOSTDOWN, 'down'), TimeoutError(),
                  BootstrapTimeout('wifi_start', 'head unit did not answer in time')):
      self.assertTrue(car_never_answered(error))
