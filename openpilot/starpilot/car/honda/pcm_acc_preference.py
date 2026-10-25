"""Opt-in for the Clarity interceptor PCM-ACC test mode (opendbc/car/honda/pcm_acc.py).

A raw param file, not a registered key, so trying it needs no params rebuild: `echo 1 > /data/params/d/ClarityPcmAccMode`
turns it on and removing the file turns it off. Read once when the car starts; it applies from the next drive.
"""
from pathlib import Path

PARAM = "ClarityPcmAccMode"


def enabled(params) -> bool:
  try:
    return Path(params.get_param_path(PARAM)).read_bytes().strip() == b"1"
  except OSError:
    return False


def attach(CI, params) -> bool:
  from opendbc.car.honda.pcm_acc import qualified
  on = CI.CC is not None and qualified(CI.CP) and enabled(params)
  if CI.CC is not None:
    CI.CC.keep_pcm_acc = on
  CI.CS.keep_pcm_acc = on
  return on
