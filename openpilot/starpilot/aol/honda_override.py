"""Night Star port: on Honda stock AOL a hard driver override is a transport withdrawal's cause (transport_pause)."""

OVERRIDE_HOLD_NS = 2_000_000_000   # longest gap between accepted temporary-EPS frames of one override


def _qualified_override(cp, cs) -> bool:
  if cp.brand != 'honda' or not cs.steeringPressed:
    return False
  from opendbc.car.honda.stock_aol import qualified as honda_stock_qualified
  return bool(honda_stock_qualified(cp, marked_only=True))


def honda_override_withdrawal(cp, cs, tp=None, axis=None) -> bool:
  """selfdrived adds no temporary-steering event while the driver steers (a hard override alone puts the Honda EPS
  in NO_TORQUE_ALERT_1), so on Honda stock AOL the driver override is the withdrawal's cause. Without this the latch
  reset and lateral waited for an LKAS press after every hard takeover (Clarity 00000055--32067800c4 seg 9 32.4 s,
  00000056--c3fdf28de7 seg 5 58.4 s). The override's session is kept for honda_override_hold."""
  if not _qualified_override(cp, cs):
    return False
  if tp is not None and axis is not None:
    tp.honda_override_held = (str(axis.sessionId), int(axis.sourceCarStateMonoTime))
  return True


def honda_override_hold(tp, cp, cs, axis, latched) -> bool:
  """The EPS fault can clear for a few frames mid-override and rise again while the driver still steers. Lateral is
  not granted again in those healthy frames, so transport_pause drops its lateral baseline, and the second rise then
  reset the latch (Clarity 00000060--8a732b781c seg 5 34.24 s, 0000005d--9880caa2c6 seg 13 0.39 s). Within one
  continuous override whose first rise was accepted, a temporary EPS fault keeps the intent. Only intent: the panda
  still refuses torque during the fault, and lateral returns through the normal grant once it clears."""
  held = getattr(tp, 'honda_override_held', None)
  if held is None:
    return False
  if (not _qualified_override(cp, cs) or str(axis.sessionId) != held[0] or
      not 0 <= axis.sourceCarStateMonoTime - held[1] <= OVERRIDE_HOLD_NS):
    tp.honda_override_held = None   # the driver let go, a new session, or too long without an accepted frame
    return False
  if (not latched or tp.lateral_baseline_ns or tp.failed or tp.paused or tp.session != held[0] or
      not cs.steerFaultTemporary or cs.steerFaultPermanent or not cs.canValid or cs.canTimeout or
      str(axis.faultReason) != 'none'):
    return False
  tp.honda_override_held = (held[0], int(axis.sourceCarStateMonoTime))
  return True
