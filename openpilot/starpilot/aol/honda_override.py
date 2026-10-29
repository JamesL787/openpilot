"""Night Star port: on Honda stock AOL a hard driver override is a transport withdrawal's cause (transport_pause)."""


def honda_override_withdrawal(cp, cs) -> bool:
  """selfdrived adds no temporary-steering event while the driver steers (a hard override alone puts the Honda EPS
  in NO_TORQUE_ALERT_1), so on Honda stock AOL the driver override is the withdrawal's cause. Without this the latch
  reset and lateral waited for an LKAS press after every hard takeover (Clarity 00000055--32067800c4 seg 9 32.4 s,
  00000056--c3fdf28de7 seg 5 58.4 s)."""
  if cp.brand != 'honda' or not cs.steeringPressed:
    return False
  from opendbc.car.honda.stock_aol import qualified as honda_stock_qualified
  return bool(honda_stock_qualified(cp, marked_only=True))
