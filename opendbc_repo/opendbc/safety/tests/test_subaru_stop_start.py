import unittest
from opendbc.car import structs
from opendbc.safety.tests.common import CANPackerSafety
from opendbc.safety.tests.libsafety import libsafety_py


class TestSubaruStopStartNative(unittest.TestCase):
  def setUp(self):
    self.safety = libsafety_py.libsafety

  def tearDown(self):
    self.safety.init_tests()
    self.safety.set_alternative_experience(0)
    self.safety.set_safety_hooks(structs.CarParams.SafetyModel.noOutput, 0)

  def configure(self, word, experience=0):
    self.word = word
    self.safety.init_tests()
    self.safety.set_timer(0)
    self.safety.set_alternative_experience(experience)
    self.safety.set_safety_hooks(structs.CarParams.SafetyModel.subaru, word)
    self.packer = CANPackerSafety('subaru_global_2017_generated')
    self.now = 1_000_000
    self.count = 0

  def feed(self, state=1, gear=4, moving=False, gas=False, fault=False, cruise=False, omit=()):
    self.now += 10_000
    self.safety.set_timer(self.now)
    main = 1 if self.word == 465 else 0
    sources = [('Throttle', {'Throttle_Pedal': int(gas)}, main), ('Steering_Torque', {'Steer_Error_1': int(fault)}, 0), ('Steering_2', {}, 0),
               ('Wheel_Speeds', dict.fromkeys(('FL', 'FR', 'RL', 'RR'), 1 if moving else 0), 1),
               ('ES_Distance', {}, 1), ('Brake_Status', {}, 1), ('ES_Status', {'Cruise_Activated': int(cruise)}, 1), ('ES_DashStatus', {'Cruise_On': 1}, 2),
               ('Dashlights', {'COUNTER': self.count % 16}, 1),
               ('Transmission', {'COUNTER': self.count % 16, 'Gear': gear}, main),
               ('Engine_Stop_Start', {'Counter': self.count % 16, 'STOP_START_STATE': state}, 1)]
    for name, fields, bus in sources:
      if name in omit:
        continue
      packet = self.packer.make_can_msg_safety(name, bus, fields)
      self.safety.safety_rx_hook(packet)
      if name == 'Dashlights':
        self.template = bytes(packet.data[0:8])
    self.count += 1
    self.safety.safety_tick()

  def command(self, *, bus=1, changed=False):
    data = bytearray(self.template)
    data[1] = (data[1] & 0xf0) | ((data[1] + 1) & 15)
    data[6] |= 0x40
    if changed:
      data[7] ^= 1
    data[0] = (0x93 + sum(data[1:])) & 255
    return libsafety_py.make_CANPacket(0x390, bus, bytes(data))

  def test_real_native_profile_positive_wrong_bus_payload_and_already_off(self):
    for word in (401, 465):
      self.configure(word)
      for _ in range(12):
        self.feed()
      self.assertFalse(self.safety.get_controls_allowed())
      self.assertFalse(self.safety.safety_tx_hook(self.command(bus=0)))
      self.assertFalse(self.safety.safety_tx_hook(self.command(changed=True)))
      self.assertTrue(self.safety.safety_tx_hook(self.command()))
      for _ in range(5):
        self.feed()
      self.feed(state=3)
      self.assertFalse(self.safety.safety_tx_hook(self.command()))
    for state, gear, moving in ((0, 4, False), (3, 4, False), (1, 3, False), (1, 4, True)):
      self.configure(401)
      for _ in range(12):
        self.feed(state=state, gear=gear, moving=moving)
      self.assertFalse(self.safety.safety_tx_hook(self.command()))

  def ready(self, word=401, experience=0):
    self.configure(word, experience)
    for _ in range(12):
      self.feed()

  def test_exact_optional_word_and_experience_only(self):
    for experience in (0, 32):
      self.ready(experience=experience)
      self.assertTrue(self.safety.safety_tx_hook(self.command()))
    for word in (0, 17, 145, 177, 256, 400, 402, 403, 464, 466, 467, 657, 2225, 65535):
      self.ready(word)
      self.assertFalse(self.safety.safety_tx_hook(self.command()), word)
    for experience in (1, 64):
      self.ready(experience=experience)
      self.assertFalse(self.safety.safety_tx_hook(self.command()))

  def test_exact_source_payload_counter_checksum_and_length(self):
    for byte in range(8):
      self.ready()
      packet = self.command()
      data = bytearray(packet.data[0:8])
      data[byte] ^= 1
      if byte:
        data[0] = (0x93 + sum(data[1:])) & 255
      self.assertFalse(self.safety.safety_tx_hook(libsafety_py.make_CANPacket(0x390, 1, bytes(data))))
    self.ready()
    self.assertFalse(self.safety.safety_tx_hook(libsafety_py.make_CANPacket(0x390, 1, bytes(self.command().data[0:7]))))
    self.assertTrue(self.safety.safety_tx_hook(self.command()))
    self.assertFalse(self.safety.safety_tx_hook(self.command()))

  def test_each_source_stale_missing_duplicate_conflict_and_invalid(self):
    for name in ('Dashlights', 'Transmission', 'Engine_Stop_Start', 'ES_Distance'):
      self.configure(401)
      for _ in range(40):
        self.feed(omit=(name,))
      if name != 'Dashlights':
        self.assertFalse(self.safety.safety_tx_hook(self.command()), name)
      self.ready()
      for _ in range(31):
        self.feed(omit=(name,))
      self.assertFalse(self.safety.safety_tx_hook(self.command()), name)
    for changed in (False, True):
      self.ready()
      data = bytearray(self.template)
      data[7] ^= int(changed)
      data[0] = (0x93 + sum(data[1:])) & 255
      self.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x390, 1, bytes(data)))
      self.assertEqual(bool(self.safety.safety_tx_hook(self.command())), not changed)
    for length in (7, 8):
      self.ready()
      data = bytearray(self.template)
      data[0] ^= 1
      self.safety.safety_rx_hook(libsafety_py.make_CANPacket(0x390, 1, bytes(data[:length])))
      self.assertFalse(self.safety.safety_tx_hook(self.command()))

  def test_pulse_spacing_budget_startup_window_and_driver_abort(self):
    self.ready()
    self.assertTrue(self.safety.safety_tx_hook(self.command()))
    self.feed()
    self.assertFalse(self.safety.safety_tx_hook(self.command()))
    for _ in range(4):
      self.feed()
    self.assertTrue(self.safety.safety_tx_hook(self.command()))
    for _ in range(26):
      self.feed()
    self.assertFalse(self.safety.safety_tx_hook(self.command()))
    self.ready()
    self.now = 11_000_000
    self.feed()
    self.assertFalse(self.safety.safety_tx_hook(self.command()))
    for driver in ('gas', 'moving', 'fault', 'cruise'):
      self.ready()
      self.feed(**{driver: True})
      self.feed()
      self.assertFalse(self.safety.safety_tx_hook(self.command()), driver)
