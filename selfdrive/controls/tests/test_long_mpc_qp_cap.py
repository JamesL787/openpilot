import numpy as np
import pytest

from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib import long_mpc
from openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc import LongitudinalMpc


class _CapSolver:
  """Wraps the real solver; reports qp_stat from a script, one entry per solve()."""
  def __init__(self, solver, qp_stats):
    self._solver = solver
    self._qp_stats = list(qp_stats)
    self.solves = 0

  def solve(self):
    self.solves += 1
    return self._solver.solve()

  def get_stats(self, field):
    if field == 'statistics':
      stat = self._qp_stats[min(self.solves, len(self._qp_stats)) - 1]
      return np.array([[0.0, 1.0], [0.0, float(stat)], [0.0, 10.0 if stat == long_mpc.ACADOS_QP_MAXITER else 4.0]])
    return self._solver.get_stats(field)

  def __getattr__(self, name):
    return getattr(self._solver, name)


@pytest.mark.parametrize("qp_stats, solves, resolved", [
  ([0], 1, False),
  ([long_mpc.ACADOS_QP_MAXITER, 0], 2, True),
  # still capped after the second solve: published, no third solve
  ([long_mpc.ACADOS_QP_MAXITER, long_mpc.ACADOS_QP_MAXITER], 2, True),
])
def test_qp_iter_cap_resolves_once(qp_stats, solves, resolved):
  mpc = LongitudinalMpc()
  stub = _CapSolver(mpc.solver, qp_stats)
  mpc.solver = stub
  mpc.run()
  assert stub.solves == solves
  assert mpc.qp_cap_resolved is resolved


def test_qp_iter_cap_resolve_can_be_turned_off(monkeypatch):
  monkeypatch.setattr(long_mpc, "MPC_QP_CAP_RESOLVE", False)
  mpc = LongitudinalMpc()
  stub = _CapSolver(mpc.solver, [long_mpc.ACADOS_QP_MAXITER])
  mpc.solver = stub
  mpc.run()
  assert stub.solves == 1
  assert not mpc.qp_cap_resolved


def test_real_solver_statistics_layout():
  # the guard reads row 1 (qp_stat) of the last column; a converged trivial solve is not a cap
  mpc = LongitudinalMpc()
  mpc.run()
  stats = mpc.solver.get_stats('statistics')
  assert stats.shape[0] >= 3
  assert not mpc.qp_hit_iter_cap()
