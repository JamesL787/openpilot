import tempfile
import unittest

from opendbc.car import structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.common.params import Params
from openpilot.starpilot.galaxy.settings import AuthorityContext, SettingsGateway


def vehicle(car=CAR.HONDA_CLARITY, fw_version=b'39990-TRW,A020\x00\x00'):
  car_fw = [structs.CarParams.CarFw(ecu=structs.CarParams.Ecu.eps, fwVersion=fw_version, address=0x18DA30F1, subAddress=0)]
  cp = CarInterface.get_params(car, {0: {}, 1: {}, 2: {}}, car_fw, False, False, False)
  cp.carFw = car_fw
  return cp


class TestNightStarSettings(unittest.TestCase):
  def setUp(self):
    temporary = tempfile.TemporaryDirectory()
    self.addCleanup(temporary.cleanup)
    self.params = Params(temporary.name)
    self.use(vehicle(), parked=False)

  def use(self, cp, *, parked):
    self.context = AuthorityContext(parked, cp, cp.to_bytes())
    self.gateway = SettingsGateway(self.params, self, clock=lambda: 100.0)

  def sample(self) -> AuthorityContext:
    return self.context

  def page(self, page='night_star'):
    return self.gateway.page(page, 'session', b'generation')

  def labels(self):
    return [row['label'] for row in self.page()['rows']]

  def set(self, label, value=None, direction=0):
    page = self.page()
    index = next(i for i, row in enumerate(page['rows']) if row['label'] == label)
    intent = self.gateway.preview(page['view'], index, direction, 'session', b'generation', value=value)
    return self.gateway.confirm(intent['intent'], 'session', b'generation')

  def test_the_hub_links_the_page(self):
    self.assertIn('Night Star', {row['label'] for row in self.page('hub')['rows']})

  def test_clarity_rows_without_fades_filters_or_pid_trims(self):
    labels = self.labels()
    # every calibrated image steers with LatControlHondaEps, so there is no controller choice, but there is its rate limit
    self.assertNotIn('Honda EPS Controller', labels)
    self.assertEqual(labels[0], 'Steering Angle Rate Limit')
    self.assertIn('Override Torque Threshold', labels)
    self.assertNotIn('Disable Seatbelt Check', labels)
    self.assertFalse(any('Fade' in label or 'Filter' in label or 'Scale' in label for label in labels))

  def test_settings_are_live_onroad(self):
    self.assertTrue(self.set('Override Torque Threshold', '1840'))
    self.assertEqual(self.params.get('HondaDriverOverrideThreshold'), 1840)

  def test_off_grid_saved_rate_limit_steps_from_where_it_is(self):
    self.params.put('HondaEpsAngleRateLimit', 219, block=True)
    row = next(row for row in self.page()['rows'] if row['label'] == 'Steering Angle Rate Limit')
    self.assertEqual(row['value'], '219')
    self.assertTrue(self.set('Steering Angle Rate Limit', direction=1))   # the Clarity saved 219, off the 10 grid
    self.assertEqual(self.params.get('HondaEpsAngleRateLimit'), 229)

  def test_the_steer_rate_limiter_has_no_rows(self):
    labels = self.labels()
    self.assertFalse([label for label in labels if 'Rate Limiter' in label or label.startswith('Rate Limit ')])
    # the page's save path refuses the limiter's keys too, so nothing can turn it on from here
    from openpilot.starpilot.ui.night_star_feature import KEYS
    for key in ('HondaSteerDeltaLimiter', 'HondaSteerDeltaUp', 'HondaSteerDeltaDown'):
      self.assertNotIn(key, KEYS)

  def test_every_calibrated_image_gets_the_rate_limit_and_no_controller_choice(self):
    self.use(vehicle(CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C020\x00\x00'), parked=True)
    labels = self.labels()
    self.assertNotIn('Honda EPS Controller', labels)
    self.assertEqual(labels[0], 'Steering Angle Rate Limit')

  def test_uncalibrated_modified_image_has_no_rate_limit(self):
    self.use(vehicle(CAR.HONDA_CIVIC_BOSCH, b'39990-TGG,A020\x00\x00'), parked=True)   # still on the modified PID
    labels = self.labels()
    self.assertNotIn('Steering Angle Rate Limit', labels)
    self.assertIn('Override Torque Threshold', labels)

  def test_other_cars_get_no_page_link(self):
    self.use(vehicle(fw_version=b'39990-TRW-A010\x00\x00'), parked=True)   # a stock Clarity EPS
    self.assertEqual(self.labels(), [])
    self.assertNotIn('Night Star', {row['label'] for row in self.page('hub')['rows']})


if __name__ == "__main__":
  unittest.main()
