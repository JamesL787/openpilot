"""Real controller checkpoints recover after missing optional evidence."""
from unittest import mock

import pytest
from opendbc.car.car_helpers import interfaces
from opendbc.car.hyundai.values import CAR as HKG
from opendbc.car.toyota.values import CAR as TOYOTA
from opendbc.car.honda.values import CAR as HONDA
from openpilot.cereal import messaging
from openpilot.starpilot.flm.learning_wire import read_control
from openpilot.starpilot.flm.runtime_adapter_registry import objective_key
from openpilot.starpilot.flm.steerlearnerd import production_adapter_for_evidence
from openpilot.starpilot.flm.tests.test_registered_controls_global import controls_for
from openpilot.starpilot.flm.tests.test_live_calibration_paths import live_frame, BASE


@pytest.mark.parametrize('vehicle,mode', [(HKG.HYUNDAI_IONIQ_6, 'starpilot'),
  (TOYOTA.TOYOTA_RAV4_TSS2, 'standard'), (HONDA.HONDA_CIVIC, None)])
@pytest.mark.parametrize('missing', ['vehicle_health', 'stage_trace'])
def test_actual_capture_resumes_with_original_checkpoint(vehicle, mode, missing):
  cp = interfaces[vehicle].get_non_essential_params(vehicle)
  with controls_for(cp, mode, True) as controls:
    adapter = None
    previous = None
    before = controls.CP.as_builder().to_bytes()
    for tick in range(165):
      now = BASE + tick * 10_000_000
      output = live_frame(controls, tick, 'a' * 32, can_valid=not (tick == 145 and missing == 'vehicle_health'))
      runtime = controls.global_learning
      if tick == 145 and missing == 'stage_trace':
        runtime.observation.stage = None
      controls.pm.send.reset_mock()
      with mock.patch('openpilot.selfdrive.controls.controlsd.time.monotonic_ns', return_value=now):
        controls.publish(*output)
      event = next(call.args[1] for call in controls.pm.send.call_args_list if call.args[0] == 'starpilotLateralState')
      event = messaging.log_from_bytes(event.to_bytes())
      if tick == 145:
        assert event.starpilotLateralState.learningEvidence.version == 0
        assert runtime.applied_coordinates == (0., 0.)
        continue
      if not event.starpilotLateralState.learningEvidence.version:
        assert tick < 100
        continue
      evidence = read_control(event)
      if tick < 100:
        continue
      if adapter is None:
        if not evidence.replay_snapshot:
          continue
        adapter = production_adapter_for_evidence(controls.CP, evidence, objective_key(evidence), source=runtime.source)
        assert adapter is not None
      if tick == 146:
        assert evidence.replay_snapshot, 'Missing frames require a fresh actual pre-update state'
        assert previous is not None and evidence.snapshot_sequence == previous.snapshot_sequence + 1
      prepared = adapter.prepare_control(evidence)
      if prepared is None:
        from openpilot.starpilot.flm.learner_factory import _frame
        from openpilot.starpilot.flm.native_refinement_wire import valid_inputs
        actual = _frame(evidence)
        print('DIAG', tick, 'frame', actual.frame_sequence, 'last', adapter.replay.last_sequence,
          'stamp', actual.control_ns, 'last_ns', adapter.replay.last_ns, 'checkpoint', adapter.replay.checkpoint_ns,
          'inputs_valid', valid_inputs(actual.inputs), 'snapshot_sequence', evidence.snapshot_sequence,
          'adapter_sequence', adapter.snapshot_sequence, 'evidence_identity', evidence.identity,
          'adapter_identity', adapter.identity, 'stage', evidence.stage_schema_revision, adapter.raw_stage_revision)
      assert prepared is not None, (tick, adapter.replay.failed)
      if tick > 146:
        assert not evidence.replay_snapshot, 'Continuous recovery must not copy a checkpoint every frame'
      previous = evidence
    assert adapter is not None and len(adapter.replay.records) >= 30
    assert controls.CP.as_builder().to_bytes() == before
    assert runtime.applied_coordinates == (0., 0.)
