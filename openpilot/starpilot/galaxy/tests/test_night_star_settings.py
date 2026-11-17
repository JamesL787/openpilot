import tempfile
import unittest

from opendbc.car import structs
from opendbc.car.honda.interface import CarInterface
from opendbc.car.honda.values import CAR
from openpilot.common.params import Params
from openpilot.starpilot.galaxy.settings import AuthorityContext, SettingsChanged, SettingsGateway


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

  def test_clarity_rows_without_filters_or_pid_trims(self):
    labels = self.labels()
    # every calibrated image steers with LatControlHondaEps, so there is no controller choice, but there is its rate limit
    self.assertNotIn('Honda EPS Controller', labels)
    self.assertEqual(labels[0], 'Steering Angle Rate Limit')
    self.assertIn('Override Torque Threshold', labels)
    self.assertEqual(labels[-1], 'Disable Seatbelt Check')
    self.assertFalse(any('Filter' in label or 'Scale' in label for label in labels))

  def test_override_fades_sit_in_press_order(self):
    labels = self.labels()
    order = ['Override Torque Threshold', 'Override Fade Down', 'Torque During Override', 'Override Fade Up']
    self.assertEqual([label for label in labels if label in order], order)
    rows = {row['label']: row for row in self.page()['rows']}
    self.assertEqual(rows['Override Fade Down']['value'], '0.0')   # the registered defaults, nothing saved
    self.assertEqual(rows['Override Fade Up']['value'], '0.5')

  def test_override_fades_are_live_onroad(self):
    self.assertTrue(self.set('Override Fade Up', '1.2'))
    self.assertAlmostEqual(self.params.get('HondaOverrideFadeUpSecs'), 1.2)
    self.assertTrue(self.set('Override Fade Down', '0.3'))
    self.assertAlmostEqual(self.params.get('HondaOverrideFadeDownSecs'), 0.3)
    self.assertTrue(self.set('Override Fade Up', direction=1))   # one 0.1 s step
    self.assertAlmostEqual(self.params.get('HondaOverrideFadeUpSecs'), 1.3)

  def test_override_fades_refuse_values_the_car_controller_would_clamp(self):
    with self.assertRaises(SettingsChanged):
      self.set('Override Fade Up', '10.5')
    with self.assertRaises(SettingsChanged):
      self.set('Override Fade Down', '-0.1')
    self.assertIsNone(self.params.get('HondaOverrideFadeUpSecs'))   # nothing saved, so the 0.5 s default still holds
    self.assertIsNone(self.params.get('HondaOverrideFadeDownSecs'))

  def test_saved_fade_survives_the_page(self):
    self.params.put('HondaOverrideFadeUpSecs', 1.5, block=True)   # an older nrdr-style value
    row = next(row for row in self.page()['rows'] if row['label'] == 'Override Fade Up')
    self.assertEqual(row['value'], '1.5')

  def test_settings_are_live_onroad(self):
    self.assertTrue(self.set('Override Torque Threshold', '1840'))
    self.assertEqual(self.params.get('HondaDriverOverrideThreshold'), 1840)
    self.assertTrue(self.set('Disable Seatbelt Check', 'On'))
    self.assertTrue(self.params.get_bool('DisableSeatbeltCheck'))

  def test_off_grid_saved_rate_limit_steps_from_where_it_is(self):
    self.params.put('HondaEpsAngleRateLimit', 219, block=True)
    row = next(row for row in self.page()['rows'] if row['label'] == 'Steering Angle Rate Limit')
    self.assertEqual(row['value'], '219')
    self.assertTrue(self.set('Steering Angle Rate Limit', direction=1))   # the Clarity saved 219, off the 10 grid
    self.assertEqual(self.params.get('HondaEpsAngleRateLimit'), 229)

  def test_clarity_has_angle_mode_on_by_default(self):
    row = next(row for row in self.page()['rows'] if row['label'] == 'Angle Mode')
    self.assertEqual((row['value'], row.get('default_value', 'On')), ('On', 'On'))
    self.assertTrue(self.set('Angle Mode', 'Off'))
    self.assertFalse(self.params.get_bool('HondaClarityAngleMode'))

  def test_angle_mode_is_clarity_only(self):
    self.use(vehicle(CAR.HONDA_CIVIC_BOSCH, b'39990-TBA,C020\x00\x00'), parked=True)
    self.assertNotIn('Angle Mode', self.labels())

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
    self.assertIn('Override Fade Up', labels)   # the car controller fades on every modified EPS, calibrated or not

  def test_other_cars_see_only_the_seatbelt_check(self):
    self.use(vehicle(fw_version=b'39990-TRW-A010\x00\x00'), parked=True)   # a stock Clarity EPS
    self.assertEqual(self.labels(), ['Disable Seatbelt Check'])


if __name__ == "__main__":
  unittest.main()
