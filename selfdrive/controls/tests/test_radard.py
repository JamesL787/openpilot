import pytest

from openpilot.selfdrive.controls.radard import KalmanParams, Track


def test_new_track_does_not_turn_startup_velocity_gap_into_braking():
  track = Track(19, 6.0, KalmanParams(0.05))

  # Bosch-A first-sighting vRel=0: vLead is temporarily the ego speed.
  track.update(28.9, 0.0, 0.0, 6.0, True)
  assert track.aLeadK == pytest.approx(0.0)

  # The next sample is a stopped lead. Seed from it; do not call the Kalman
  # transition with the artificial 6 -> 0 m/s jump.
  track.update(28.4, 0.0, -6.5, -0.4, True)
  assert track.aLeadK == pytest.approx(0.0)
  assert track.vLeadK == pytest.approx(-0.4)

  # Subsequent samples are filtered normally, but the startup artifact is gone.
  track.update(27.8, 0.0, -5.5, 0.4, True)
  assert track.aLeadK > -1.0
