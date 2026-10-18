"""pytest plugin for run_eps_tests.sh: run the Honda EPS controller tests on a Mac against THIS checkout.

The repo's conftest points selfdrive/ imports at the .host_runtime mirror, which can hold a stale copy of the code, so
a plain `pytest` can pass against old code. This plugin is used with --noconftest instead: it puts this checkout first
on sys.path and stubs the two device-only modules the lateral tests import (no Mac-built binaries are copied in).
"""
import os
import sys
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
for path in (os.path.join(ROOT, 'opendbc_repo'), ROOT):
  if path not in sys.path:
    sys.path.insert(0, path)


def _stub(name, **attrs):
  module = types.ModuleType(name)
  module.__dict__.update(attrs)
  sys.modules[name] = module


class _Pose:  # latcontrol only uses it as a type
  pass


class _Params:
  def __init__(self, *args, **kwargs):
    self.d = {}

  def get(self, key, *args, **kwargs):
    return self.d.get(key)

  def get_bool(self, key, *args, **kwargs):
    return self.d.get(key) in ("1", b"1", True)

  def put(self, key, val, *args, **kwargs):
    self.d[key] = val

  def put_bool(self, key, val, *args, **kwargs):
    self.d[key] = "1" if val else "0"


class UnknownKeyName(Exception):
  pass


_stub("openpilot.selfdrive.locationd.helpers", Pose=_Pose)
_stub("openpilot.common.params", Params=_Params, UnknownKeyName=UnknownKeyName)
