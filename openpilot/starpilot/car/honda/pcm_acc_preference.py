"""Opt-in for the Clarity interceptor PCM-ACC test mode (opendbc/car/honda/pcm_acc.py).

A plain file outside /data/params/d: manager start archives unregistered param files there (state_migration), and a
registered key would need a params rebuild. `echo 1 > /data/ClarityPcmAccMode` turns it on and removing the file turns
it off. Read once when the car starts; it applies from the next drive.
"""
from pathlib import Path

TOGGLE = Path("/data/ClarityPcmAccMode")


def enabled(path: Path = TOGGLE) -> bool:
  try:
    return path.read_bytes().strip() == b"1"
  except OSError:
    return False


def attach(CI, params, path: Path = TOGGLE) -> bool:
  from opendbc.car.honda.pcm_acc import qualified
  on = CI.CC is not None and qualified(CI.CP) and enabled(path)
  if CI.CC is not None:
    CI.CC.keep_pcm_acc = on
  CI.CS.keep_pcm_acc = on
  return on
