import json
import math
import os

# Records which learner version the saved Honda gas/wind factors belong to (ns used /data/honda_learner_meta.json;
# a separate file so ns's record cannot vouch for factors learned under star7's math).
LEARNER_META_PATH = "/data/star7_honda_gas_learner.json"


def _meta_matches(path, version):
  try:
    with open(path) as f:
      return json.load(f).get("version") == version
  except (OSError, ValueError, AttributeError):
    return False


class BoschLearningParams:
  def __init__(self, params, owner, meta_path=LEARNER_META_PATH):
    self.params = params
    self.owner = owner
    factors = []
    for key in ("HondaGasFactorParams", "HondaWindFactorParams"):
      try:
        value = float(params.get(key, return_default=True))
        if not math.isfinite(value):
          value = 1.0
      except (TypeError, ValueError, OverflowError, RuntimeError):
        value = 1.0
      factors.append(value)
    version = getattr(owner, "learner_version", None)
    if version is not None and not _meta_matches(meta_path, version):
      # Saved factors came from different learner math: start this learner from 1.0 once and record it.
      factors = [1.0, 1.0]
      params.put("HondaGasFactorParams", 1.0)
      params.put("HondaWindFactorParams", 1.0)
      try:
        tmp = meta_path + ".tmp"
        with open(tmp, "w") as f:
          json.dump({"version": version}, f)
        os.replace(tmp, meta_path)
      except OSError:
        pass
    owner.set_factors(*factors)
    self.saved = (owner.bosch_gas_factor, owner.bosch_wind_factor)

  def persist(self, frame):
    if frame > 0 and frame % 6000 == 0:
      # Learning only moves while openpilot drives the pedals; skip rewriting unchanged values.
      factors = (self.owner.bosch_gas_factor, self.owner.bosch_wind_factor)
      if factors == self.saved:
        return
      self.params.put("HondaGasFactorParams", factors[0])
      self.params.put("HondaWindFactorParams", factors[1])
      self.saved = factors
