"""Night Star port: a hard driver override on Honda stock AOL keeps the latch through the EPS temporary fault (card)."""

def _qualified_override(cp, cs) -> bool:
  if cp.brand != 'honda' or not cs.steeringPressed:
    return False
  from opendbc.car.honda.stock_aol import qualified as honda_stock_qualified
  return bool(honda_stock_qualified(cp, marked_only=True))


def honda_override_shield(owner, cp, cs, latched) -> bool:
  """card: True while a qualified Honda override that raised the temporary EPS fault with AOL latched goes on. The
  transport tracker and the native-withdrawal check each see that fault in their own way, and either one clearing the
  latch left lateral waiting for an LKAS press after the takeover (Clarity 00000067--95d8a118bd seg 19 1152.3 s: one
  fault frame, 50 ms clear, second rise). While the shield is up card feeds neither into the latch; it drops when the
  driver lets go. Native rejection, disabling events, a permanent fault, CAN invalid or timeout, an ACC fault and the
  driver's own buttons still clear the latch, and the panda still refuses torque during the fault."""
  if not _qualified_override(cp, cs) or cs.steerFaultPermanent or not cs.canValid or cs.canTimeout or cs.accFaulted:
    owner.honda_override_shielded = False
  elif cs.steerFaultTemporary and latched:
    owner.honda_override_shielded = True
  return bool(getattr(owner, 'honda_override_shielded', False))
