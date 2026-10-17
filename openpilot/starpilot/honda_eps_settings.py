"""Honda EPS settings that carry across StarPilot 7.0's first start.

7.0's first start (state_migration.prepare_manager_start) archives every saved setting outside OPERATIONAL_KEYS and
starts fresh. The Honda EPS tuning below is kept instead: it is per-car calibration, not a StarPilot preference.
Settings saved under vfn's older names are renamed first, as vfn's manager does, so they are not lost as unknown
keys.
"""
from pathlib import Path

# old name -> current name, as vfn's manager renamed them. The old names are the literal keys still saved on cars, so
# they stay spelled exactly as they were.
HONDA_EPS_KEY_RENAMES = {
  "HondaTorqueLowPassFilter": "HondaTorqueOutputLowPassFilter",
  "HondaLpfTauLowSpeed": "HondaTorqueOutputLpfTauLowSpeed",
  "HondaLpfTauStandard": "HondaTorqueOutputLpfTauStandard",
  "HondaLpfTauHighway": "HondaTorqueOutputLpfTauHighway",
  "NrdrLatUseFirmwareVgr": "HondaEpsFirmwareVgr",
  "NrdrLatAngleRateLimit": "HondaEpsAngleRateLimit",
  "NrdrDriverOverrideThreshold": "HondaDriverOverrideThreshold",
  "NrdrMinSteerSpeed": "HondaMinSteerSpeed",
}

HONDA_EPS_PRESERVED_KEYS = frozenset({
  "HondaEpsAngleRateLimit", "HondaEpsFirmwareVgr", "HondaOverrideFadeUpSecs",
  "HondaTorqueOutputLowPassFilter", "HondaTorqueOutputLpfTauLowSpeed", "HondaTorqueOutputLpfTauStandard",
  "HondaTorqueOutputLpfTauHighway",
  "LatPScaleLowSpeed", "LatPScaleStandard", "LatPScaleHighway",
  "LatIScaleLowSpeed", "LatIScaleStandard", "LatIScaleHighway",
  "LatFScaleLowSpeed", "LatFScaleStandard", "LatFScaleHighway",
  "HondaDriverOverrideThreshold", "HondaMinSteerSpeed", "HondaOverrideFadeDownSecs", "HondaOverrideTorqueScale",
  "HondaDriverAssistDuringOverride", "HondaSteerDeltaLimiter", "HondaSteerDeltaUp", "HondaSteerDeltaDown",
})


def migrate_honda_eps_param_names(params) -> list[str]:
  """Move each old-name value to its current name unless that is already set, then remove the old file."""
  renamed = []
  for old_key, new_key in HONDA_EPS_KEY_RENAMES.items():
    old_path = Path(params.get_param_path(old_key))
    try:
      raw = old_path.read_bytes()
    except OSError:
      continue
    if raw and params.get(new_key) is None:
      try:
        params.put(new_key, params.cpp2python(new_key, raw), block=True)
        renamed.append(f"{old_key}->{new_key}")
      except (TypeError, ValueError, UnicodeError):
        pass
    try:
      old_path.unlink()
    except OSError:
      pass
  return renamed
