from opendbc.car.fw_query_definitions import LiveFwVersions, OfflineFwVersions
from opendbc.car.structs import CarParams


def validate_fw_match(candidate: str, observed: LiveFwVersions, versions: OfflineFwVersions) -> bool:
  if candidate != "HONDA_CLARITY":
    return True
  # Real Clarities do not always answer the fwdRadar query (this car answers EPS, VSA and SRS only, on every logged
  # drive), so the radar is checked when present but is not required.
  required = {CarParams.Ecu.eps, CarParams.Ecu.vsa}
  expected = versions.get(candidate, {})
  found = set()
  for (ecu, address, subaddress), allowed in expected.items():
    actual = observed.get((address, subaddress), set())
    if actual:
      if not actual.issubset(allowed):
        return False
      found.add(ecu)
  return required.issubset(found)
