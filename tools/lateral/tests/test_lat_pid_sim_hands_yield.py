import numpy as np

from openpilot.tools.lateral import lat_pid_sim as S


def test_hands_yield_is_symmetric_and_falls_with_hand_torque():
  tq = np.array([0.0, 400.0, 1000.0, 1800.0, 2300.0, 4000.0])
  k = S.hands_yield(tq)
  assert np.allclose(S.hands_yield(-tq), k)
  assert k[0] == 1.0 and k[1] == 1.0 and k[-1] == 0.0
  assert np.all(np.diff(k) <= 0)


def test_hands_yield_round_trips_through_plant_json():
  p = S.Plant.from_json(S.Plant(np.zeros(9)).to_json())
  assert not getattr(p, "hands_yield", False)
  p.hands_yield = True
  assert S.Plant.from_json(p.to_json()).hands_yield
