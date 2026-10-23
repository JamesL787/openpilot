"""Explain the existing Civic Bosch firmware match rules without changing the matcher/database."""


def firmware_match_report(cp):
  # Import only when diagnosing H020. Disabled and unrelated startup keeps its existing import path.
  from opendbc.car.honda.fingerprints import FW_VERSIONS
  from opendbc.car.honda.values import CAR, FW_QUERY_CONFIG
  from opendbc.car.fw_query_definitions import ESSENTIAL_ECUS, ECU_NAME

  candidate = CAR.HONDA_CIVIC_BOSCH
  expected = FW_VERSIONS[candidate]
  live = {}
  for fw in cp.carFw:
    # These are the same brand/logging/address rules as fw_versions.build_fw_dict.
    if fw.brand == 'honda' and not fw.logging:
      live.setdefault((fw.address, fw.subAddress or None), set()).add(bytes(fw.fwVersion))
  rows = []
  for (ecu, address, subaddress), versions in expected.items():
    observed = live.get((address, subaddress), set())
    matched = any(value in versions for value in observed)
    required = ecu in ESSENTIAL_ECUS and candidate not in FW_QUERY_CONFIG.non_essential_ecus.get(ecu, [])
    rows.append(
      {
        'ecu': ECU_NAME.get(ecu, str(ecu)),
        'address': hex(address),
        'subaddress': subaddress,
        'status': 'matched' if matched else ('mismatch' if observed else 'missing'),
        'required_when_missing': required,
        'observed_versions_hex': sorted(value.hex() for value in observed),
      }
    )
  known = {(address, subaddress) for _, address, subaddress in expected}
  for address, subaddress in sorted(live.keys() - known, key=lambda key: (key[0], key[1] or 0)):
    rows.append(
      {
        'ecu': 'unlisted',
        'address': hex(address),
        'subaddress': subaddress,
        'status': 'unlisted',
        'required_when_missing': False,
        'observed_versions_hex': sorted(value.hex() for value in live[(address, subaddress)]),
      }
    )
  return {
    'candidate': str(candidate),
    'fingerprint_source': str(cp.fingerprintSource),
    'fuzzy': cp.fuzzyFingerprint,
    'ecus': rows,
    'note': 'Database comparison only; missing optional ECUs are allowed by res. A present optional ECU must match. '
    + 'This report neither proves a physical platform nor overrides the existing firmware matcher.',
  }


def match_summary(report):
  return 'Civic Bosch ECUs: ' + '; '.join(
    f"{row['ecu']}@{row['address']}={row['status']}" + ('(required)' if row['required_when_missing'] else '(optional when missing)') for row in report['ecus']
  )
