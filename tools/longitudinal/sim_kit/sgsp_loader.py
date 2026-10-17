"""Load SGSP (StarPilot SecretGoodStarPilot) planner modules over this tree, replay only.

install() puts a finder first on sys.meta_path: any `openpilot.*` module that exists under sim_kit/sgsp/ (extracted
from starpilot/SecretGoodStarPilot by ~/sgsp_scripts/closure.py) is loaded from there; everything else
(cereal, params, realtime, swaglog, system, tools, opendbc) comes from this tree. Packages get both directories on
__path__ so a submodule missing from the SGSP extract still resolves here. Use one process per planner family.
"""
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys

KIT = os.path.dirname(os.path.abspath(__file__))
SGSP = os.path.join(KIT, "sgsp")
REPO = os.path.abspath(os.path.join(KIT, "..", "..", ".."))
KEEP_OURS = ("openpilot.cereal", "openpilot.common.params", "openpilot.common.realtime", "openpilot.common.swaglog",
             "openpilot.system", "openpilot.tools", "openpilot.third_party")


class _Finder(importlib.abc.MetaPathFinder):
  def find_spec(self, name, path=None, target=None):
    if not name.startswith("openpilot.") or name.startswith(KEEP_OURS):
      return None
    rel = name.split(".")
    base = os.path.join(SGSP, *rel)
    if os.path.isfile(base + ".py"):
      return importlib.util.spec_from_file_location(name, base + ".py")
    if os.path.isfile(os.path.join(base, "__init__.py")):
      ours = os.path.join(REPO, *rel[1:])
      locs = [base] + ([ours] if os.path.isdir(ours) else [])
      return importlib.util.spec_from_file_location(name, os.path.join(base, "__init__.py"), submodule_search_locations=locs)
    return None


class _Opendbc(importlib.machinery.PathFinder):
  """First on sys.meta_path: every `opendbc` module comes from SGSP's vendored opendbc, extracted whole into
  sgsp/opendbc_extra (`git archive starpilot/SecretGoodStarPilot opendbc_repo/opendbc`). The SGSP planner's vehicle
  policies need its newer opendbc; this tree's opendbc is unused in an SGSP process (the radar parser output arrives
  as the logged radarState)."""
  @classmethod
  def find_spec(cls, name, path=None, target=None):
    if name == "opendbc":
      return super().find_spec(name, [os.path.join(SGSP, "opendbc_extra")], target)
    return None


class _SgspFallback(importlib.abc.MetaPathFinder):
  """Last on sys.meta_path: an `openpilot.*` module found in neither sgsp/ nor this tree is extracted from SGSP on
  first use (`git show`) into sgsp/ and loaded from there."""
  _files = None

  def find_spec(self, name, path=None, target=None):
    if not name.startswith("openpilot."):
      return None
    import subprocess
    if _SgspFallback._files is None:
      _SgspFallback._files = set(open(os.path.join(SGSP, "sgsp_files.txt")).read().split())
    rel = name.split(".")[1:]
    for tail, pkg in (((*rel[:-1], rel[-1] + ".py"), False), ((*rel, "__init__.py"), True)):
      src = "openpilot/" + "/".join(tail)
      if src not in _SgspFallback._files:
        continue
      dst = os.path.join(SGSP, "openpilot", *tail)
      if not os.path.isfile(dst):
        r = subprocess.run(["git", "-C", REPO, "show", "starpilot/SecretGoodStarPilot:" + src], capture_output=True, text=True, timeout=120)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        open(dst, "w").write(r.stdout)
      return importlib.util.spec_from_file_location(name, dst, submodule_search_locations=[os.path.dirname(dst)] if pkg else None)
    return None


def install():
  assert not any(m == 'opendbc' or m.startswith('opendbc.') for m in sys.modules), 'install() before opendbc is imported'
  import openpilot  # noqa: F401  (this tree's top package)
  if not any(isinstance(f, _Finder) for f in sys.meta_path):
    sys.meta_path.insert(0, _Finder())
    sys.meta_path.insert(0, _Opendbc())
    sys.meta_path.append(_SgspFallback())
  # SGSP imports `acados.acados_template` and `openpilot.cereal`; map them onto this tree.
  import openpilot.third_party.acados as _ac
  sys.modules.setdefault("acados", _ac)
  import cereal
  sys.modules.setdefault("openpilot.cereal", cereal)
  for sub in ("log", "car", "custom", "messaging", "services"):
    try:
      m = importlib.import_module(f"cereal.{sub}") if sub in ("messaging", "services") else getattr(cereal, sub)
      sys.modules.setdefault(f"openpilot.cereal.{sub}", m)
    except Exception:
      pass
