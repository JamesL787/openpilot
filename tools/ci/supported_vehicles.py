"""Which vehicle tests CI runs.

The fork supports the honda brand (Honda and Acura). Every other brand is forced to dashcam mode by
opendbc.car.supported_brands, so CI does not run test files that belong to one of those brands. The files stay
in the tree: they arrive through upstream syncs and are left untouched so the syncs keep applying cleanly.

A file belongs to an unsupported brand when it sits in that brand's car directory or its path carries one of the
brand or model words below. In a brand-neutral file, a test whose own name carries one of those words is left out
too. Everything else, including the tests that walk every platform, always runs.
"""

import re
from pathlib import PurePosixPath

# Kept equal to opendbc.car.supported_brands.SUPPORTED_BRANDS by tools/ci/tests/test_supported_vehicles.py. It is
# repeated here so the suite runners can pick their targets before any vehicle code is imported.
SUPPORTED_BRANDS = frozenset({"honda"})
SUPPORTED_WORDS = frozenset({"honda", "acura"})

# Directory names under opendbc/car and starpilot/car. "body" and "mock" are not vehicles a user drives.
UNSUPPORTED_BRAND_DIRECTORIES = frozenset({
  "body", "byd", "chrysler", "ford", "gm", "hyundai", "mazda", "mg", "nissan", "psa", "rivian", "subaru", "tesla",
  "toyota", "volkswagen", "volvo",
})

# Words that only ever name another brand or one of its models. Ambiguous words (cc, ram, mg, canfd, body) are
# left out on purpose: a missed file only costs CI time, a wrong match would drop a test the fork needs.
UNSUPPORTED_WORDS = frozenset({
  "bluepilot", "ford",
  "bolt", "buick", "cadillac", "chevrolet", "gm", "gmc", "trax", "volt",
  "elantra", "ev6", "ev9", "forte", "g70", "g90", "genesis", "gv60", "gv70", "hkg", "hyundai", "ioniq", "ioniq5pe",
  "ioniq6", "kia", "kona", "nexo", "niro", "palisade", "scc", "sonata", "sportage", "stinger",
  "chrysler", "jeep",
  "mazda", "nissan", "rivian", "subaru",
  "preap", "tesla",
  "corolla", "lexus", "prius", "rav4", "rav4h", "sdsu", "toyota", "tss2",
  "meb", "mqb", "volkswagen", "vw",
  "byd", "polestar", "psa", "volvo",
})


# Brand-neutral names whose every case drives another brand's car through the real startup path, so they now see
# dashcam mode. Value: the brand they exercise.
UNSUPPORTED_FILES = {
  "openpilot/starpilot/tests/test_captured_adrv_diagnostic_startup.py": "hyundai",
  "openpilot/starpilot/tests/test_vehicle_preferences.py": "gm",
}


def unsupported_brand(target: str) -> str | None:
  """Return the word that ties a test target to an unsupported brand, or None when CI should run it."""
  path = PurePosixPath(target.split("::", 1)[0])
  for file, brand in UNSUPPORTED_FILES.items():
    if path.as_posix().endswith(file):
      return brand
  parts = path.parts
  if set(re.split(r"[^a-z0-9]+", path.stem.lower())) & SUPPORTED_WORDS:
    return None
  for index, part in enumerate(parts[:-1]):
    if part == "car" and index + 1 < len(parts) - 1:
      directory = parts[index + 1]
      if directory in SUPPORTED_BRANDS:
        return None
      if directory in UNSUPPORTED_BRAND_DIRECTORIES:
        return directory
  words = {word for part in parts for word in re.split(r"[^a-z0-9]+", PurePosixPath(part).stem.lower())}
  unsupported = UNSUPPORTED_WORDS
  if "safety" in parts[:-1]:
    # opendbc/safety/tests names one file per safety mode, so the short brand names are unambiguous there.
    unsupported = unsupported | UNSUPPORTED_BRAND_DIRECTORIES
  matched = sorted(words & unsupported)
  if matched:
    return matched[0]
  # A brand-neutral file can still hold one brand's cases: test_ev6_cancel_... in a shared module, for example.
  return unsupported_test_name(target.split("::", 1)[1]) if "::" in target else None


def unsupported_test_name(name: str) -> str | None:
  """The unsupported brand word in a test function, method or class name, parameters ignored."""
  words = set(re.split(r"[^a-z0-9]+", name.split("[", 1)[0].lower()))
  if words & SUPPORTED_WORDS:
    return None
  matched = sorted(words & UNSUPPORTED_WORDS)
  return matched[0] if matched else None


def supported(target: str) -> bool:
  return unsupported_brand(target) is None


def supported_targets(targets):
  return [target for target in targets if supported(target)]
