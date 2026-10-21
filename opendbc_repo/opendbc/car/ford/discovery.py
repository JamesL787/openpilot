"""Normal-bus discovery for explicitly selected Ford CAN-FD vehicles."""
from opendbc.car.ford.values import CAR, FordFlags


def normal_bus0_queries():
  # Verify both configured and effective requests before omitting the OBD sweep.
  # All essential and as-built requests remain on bus 0. The bus-1 logging
  # request must be an exact duplicate of a bus-0 query, not unique evidence.
  from opendbc.car import fw_versions
  configured = fw_versions.FW_QUERY_CONFIGS['ford'].requests
  effective = [request for brand, _, request in fw_versions.REQUESTS if brand == 'ford']
  if not configured or not effective:
    return False

  def signature(request):
    return (tuple(request.request), tuple(request.response), request.rx_offset, frozenset(request.whitelist_ecus))
  for requests in (configured, effective):
    normal = {signature(request) for request in requests if request.bus == 0}
    if not normal or any(request.bus != 0 and (not request.logging or signature(request) not in normal)
                         for request in requests):
      return False
  return True


def normal_bus0_selection(candidate):
  return bool(candidate in CAR and CAR(candidate).config.flags & FordFlags.CANFD and
              not CAR(candidate).config.flags & FordFlags.LKA_STEERING and normal_bus0_queries())
