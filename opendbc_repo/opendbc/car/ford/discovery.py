"""Normal-bus discovery for explicitly selected Ford CAN-FD vehicles."""
from opendbc.car.ford.values import CAR, FordFlags


def normal_bus0_queries():
  # Verify both configured and effective requests before omitting the OBD sweep.
  # Essential queries use normal bus0 and its exact auxiliary Panda bus4 copy.
  # As-built remains bus0; bus1 logging cannot provide unique evidence.
  from opendbc.car import fw_versions
  configured = fw_versions.FW_QUERY_CONFIGS['ford'].requests
  effective = [request for brand, _, request in fw_versions.REQUESTS if brand == 'ford']
  if not configured or not effective:
    return False

  def signature(request):
    return (tuple(request.request), tuple(request.response), request.rx_offset, frozenset(request.whitelist_ecus))
  for requests in (configured, effective):
    normal = {signature(request) for request in requests if request.bus == 0}
    essential = {signature(request) for request in requests if request.bus == 0 and not request.logging}
    auxiliary = {signature(request) for request in requests if request.bus == 4 and not request.logging}
    if not normal or not essential or auxiliary != essential:
      return False
    for request in requests:
      if request.bus == 0:
        continue
      if request.bus == 4 and not request.logging and signature(request) in essential:
        continue
      if request.bus == 1 and request.logging and signature(request) in normal:
        continue
      return False
  return True


def normal_bus0_selection(candidate):
  return bool(candidate in CAR and CAR(candidate).config.flags & FordFlags.CANFD and
              not CAR(candidate).config.flags & FordFlags.LKA_STEERING and normal_bus0_queries())
