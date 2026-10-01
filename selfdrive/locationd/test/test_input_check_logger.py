from types import SimpleNamespace

from cereal.messaging import FrequencyTracker
from openpilot.selfdrive.locationd import helpers
from openpilot.selfdrive.locationd.helpers import InputCheckLogger

SERVICES = ('cameraOdometry', 'carState')


def fake_sm(cur_time):
  trackers = {s: FrequencyTracker(20., 20., s == 'cameraOdometry') for s in SERVICES}
  for tracker in trackers.values():
    for i in range(10):
      tracker.record_recv_time(cur_time - 0.5 + i * 0.05)
  return SimpleNamespace(valid=dict.fromkeys(SERVICES, True), alive=dict.fromkeys(SERVICES, True), freq_ok=dict.fromkeys(SERVICES, True),
                         recv_time=dict.fromkeys(SERVICES, cur_time - 0.02), freq_tracker=trackers, seen=dict.fromkeys(SERVICES, True),
                         ignore_valid=[], ignore_alive=[], _check_avg_freq=lambda s: True)


def capture(monkeypatch):
  events = []
  monkeypatch.setattr(helpers.cloudlog, 'event', lambda event, **kw: events.append((event, kw)))
  return events


def test_silent_while_inputs_ok(monkeypatch):
  events = capture(monkeypatch)
  logger, sm = InputCheckLogger('calibrationdInputsInvalid'), fake_sm(100.)
  for t in (100., 100.25, 100.5):
    logger.update(sm, t)
  assert events == []


def test_logs_each_distinct_failure_once_then_recovery(monkeypatch):
  events = capture(monkeypatch)
  logger, sm = InputCheckLogger('calibrationdInputsInvalid'), fake_sm(100.)

  sm.alive['carState'] = False
  sm.recv_time['carState'] = 99.85
  logger.update(sm, 100.)
  logger.update(sm, 100.25)  # same failure: no repeat
  assert len(events) == 1
  name, kw = events[0]
  assert name == 'calibrationdInputsInvalid' and kw['error'] and kw['not_alive'] == ['carState']
  assert 'invalid' not in kw and 'not_freq_ok' not in kw
  details = kw['details']['carState']
  assert details['age_ms'] == 150.0 and details['recent_hz'] == 20.0
  assert (details['min_hz'], details['max_hz']) == (8.0, 24.0)

  sm.freq_ok['cameraOdometry'] = False  # a different failure is logged again
  logger.update(sm, 100.5)
  assert len(events) == 2 and events[1][1]['not_freq_ok'] == ['cameraOdometry']

  sm.alive['carState'] = sm.freq_ok['cameraOdometry'] = True
  logger.update(sm, 100.75)
  assert events[2] == ('calibrationdInputsInvalidRecovered', {'failed_s': 0.75})


def test_only_configured_checks_and_extra_reasons(monkeypatch):
  events = capture(monkeypatch)
  logger, sm = InputCheckLogger('locationdInputsInvalid', checks=('invalid',)), fake_sm(100.)

  sm.alive['carState'] = False  # locationd's inputsOK ignores alive/freq
  logger.update(sm, 100., {'rejected': []})
  assert events == []

  logger.update(sm, 100.05, {'rejected': ['gyroscope']})
  assert events[0][1]['rejected'] == ['gyroscope'] and events[0][1]['details'] == {}

  sm.valid['cameraOdometry'] = False
  logger.update(sm, 100.1, {'rejected': []})
  assert events[1][1]['invalid'] == ['cameraOdometry'] and 'rejected' not in events[1][1]
  assert list(events[1][1]['details']) == ['cameraOdometry']


def test_ignored_services_are_not_reported(monkeypatch):
  events = capture(monkeypatch)
  logger, sm = InputCheckLogger('calibrationdInputsInvalid'), fake_sm(100.)
  sm.ignore_valid = ['carState']
  sm.valid['carState'] = False
  logger.update(sm, 100.)
  assert events == []


def test_silent_until_every_input_has_arrived(monkeypatch):
  events = capture(monkeypatch)
  logger, sm = InputCheckLogger('calibrationdInputsInvalid'), fake_sm(100.)
  sm.seen['carState'] = False
  sm.alive['carState'] = False
  logger.update(sm, 100.)
  assert events == []

  sm.seen['carState'] = True
  logger.update(sm, 100.25)
  assert events[0][1]['not_alive'] == ['carState']


def test_context_is_logged_but_not_a_failure(monkeypatch):
  events = capture(monkeypatch)
  logger, sm = InputCheckLogger('torquedInputsInvalid'), fake_sm(100.)
  logger.update(sm, 100., context={'max_loop_gap_ms': 52.0})
  assert events == [], "context alone never logs"

  sm.alive['carState'] = False
  logger.update(sm, 100.25, context={'max_loop_gap_ms': 104.3})
  logger.update(sm, 100.5, context={'max_loop_gap_ms': 51.0})  # same failure, new context: no repeat
  assert len(events) == 1
  assert events[0][1]['max_loop_gap_ms'] == 104.3 and events[0][1]['not_alive'] == ['carState']
