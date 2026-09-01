"""The offline analysis tool and the shipped rule must be the same function, forever.

The integrator-freeze decision is reconstructed offline from logged carControl.actuators.torque and
carOutput.actuatorsOutput.torque, because there is no spare capnp field to log it in. That is only
sound while the reconstruction and `integrator_wind_blocked()` agree exactly. This test pins that
against a fixture of real logged frames from six drives, at every threshold we have used.
"""
import numpy as np

from openpilot.selfdrive.controls.lib.latcontrol import integrator_wind_blocked

FIXTURE = "selfdrive/controls/lib/tests/wind_blocked_fixture.npy"
THRESHOLDS = (0.0, 0.15, 0.30, 0.40)


def _offline(requested, applied, threshold):
  """The vectorised form used by the offline tool. Must match the scalar rule exactly."""
  gap = np.abs(requested - applied)
  if threshold <= 0.0:
    return gap > 1e-2
  return (requested * applied < 0.0) | (gap > np.maximum(1e-2, threshold * np.abs(requested)))


class TestIntegratorWindBlocked:
  def test_matches_offline_reconstruction(self):
    data = np.load(FIXTURE)
    requested, applied = data[:, 0], data[:, 1]
    for threshold in THRESHOLDS:
      expected = _offline(requested, applied, threshold)
      for k in range(len(requested)):
        assert bool(expected[k]) == integrator_wind_blocked(float(requested[k]), float(applied[k]), threshold), \
          f"mismatch at frame {k}, threshold {threshold}: cmd={requested[k]} out={applied[k]}"

  def test_zero_threshold_is_legacy_absolute_rule(self):
    assert integrator_wind_blocked(0.30, 0.28, 0.0)      # 0.02 gap > 1e-2
    assert not integrator_wind_blocked(0.30, 0.295, 0.0)  # 0.005 gap

  def test_relative_rule_admits_shaping_and_blocks_fade(self):
    # steady turn: LPF phase lag, ~13% of command -> integrator may wind
    assert not integrator_wind_blocked(0.30, 0.26, 0.30)
    # early override fade: applied is still ramping from zero -> must not wind
    assert integrator_wind_blocked(0.30, 0.02, 0.30)

  def test_sign_reversal_always_blocks(self):
    assert integrator_wind_blocked(0.30, -0.05, 0.30)
    assert integrator_wind_blocked(-0.30, 0.05, 0.30)

  def test_tiny_commands_use_the_absolute_floor(self):
    # relative test alone would be hypersensitive near zero; the 1e-2 floor prevents that
    assert not integrator_wind_blocked(0.01, 0.005, 0.30)
