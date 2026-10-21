"""Load existing bank and stock artifacts with one explicitly selected runtime."""
import hashlib
from pathlib import Path

from openpilot.starpilot.models.runtime_bridge.bootstrap import LEGACY_REVISION, activate

BUNDLE = Path(__file__).resolve().parents[4] / 'tinygrad_model_runtime/legacy9d'
MANIFEST_SHA256 = "20ca9e77010c1ab788f2adb824103db3d595b0da8c4069d6e32b1266f7977b1f"
_GUARD_HASHES = {
  'libbounded_wait.so': '24ed559861c8636c1026cad9a244854bb2236b5ee8b91bf21c5efbf688fa4a69',
  'libusb_guards.so': '66a3dfe48ac17899862ab80160cf6dac2c9b9707234527ba0d808f3b68404114',
}
_POLICY_SHA256 = '39c3387f44b570895aab440c6afa52eeb1996c99510205c92ea774565d881b66'
_selection = None
_protection = None
# personal branch: models run on the vendored tinygrad (02e698160e, catalog.COMPILER_REVISION) with artifacts compiled
# for it on the comma, so StarPilot's pinned legacy runtime (legacy9d, 9d0446a4) is never activated here. Every caller
# then takes its no-legacy path (selected_legacy() is False), as it does off-device.
PERSONAL_VENDORED_RUNTIME = True


def prepare(role):
  global _selection
  if PERSONAL_VENDORED_RUNTIME:
    return None
  if _selection is not None and _selection.get('purpose') == 'compiler':
    raise RuntimeError('A model compiler cannot become an inference child')
  from openpilot.common.hardware import AGNOS
  if not AGNOS:
    return None
  if _selection is not None:
    if _selection['role'] != role:
      raise RuntimeError('A model child cannot change its execution role')
    return _selection
  _verify_policy()
  cache = Path('/data/starpilot-model-runtime')
  _selection = activate(BUNDLE, MANIFEST_SHA256, LEGACY_REVISION, role, cache)
  return _selection


def prepare_compiler():
  """Keep newly compiled bank artifacts on their declared compiler ABI."""
  global _selection
  if PERSONAL_VENDORED_RUNTIME:
    return None
  if _selection is not None:
    raise RuntimeError('Select the compiler runtime before model inference')
  import tempfile
  selection = activate(BUNDLE, MANIFEST_SHA256, LEGACY_REVISION, 'driving',
                       Path(tempfile.gettempdir()).resolve() / 'starpilot-model-compiler')
  selection['purpose'] = 'compiler'
  _selection = selection
  return _selection


def require_compiler():
  if PERSONAL_VENDORED_RUNTIME:
    return
  if _selection is None or _selection.get('purpose') != 'compiler':
    raise RuntimeError('Compile bank artifacts through the selected compiler entry point')


def _verify_policy():
  root = Path(__file__).parent
  policy_path = root / 'guard-policy.json'
  if policy_path.is_symlink() or not policy_path.is_file():
    raise RuntimeError('Missing model submission guard policy')
  raw = policy_path.read_bytes()
  if hashlib.sha256(raw).hexdigest() != _POLICY_SHA256:
    raise RuntimeError('Model submission guard policy changed')
  import json
  policy = json.loads(raw)
  if (policy['compiler_revision'] != LEGACY_REVISION or policy['runtime_manifest_sha256'] != MANIFEST_SHA256 or
      policy['native_abi'] != 'linux-aarch64-64bit' or set(policy['files']) !=
      {'bootstrap.py', 'qcom.py', 'usb.py', 'capture.py', 'bounded_wait.c', 'usb_guards.c',
       'libbounded_wait.so', 'libusb_guards.so'}):
    raise RuntimeError('Model submission guard identity mismatch')
  for name, expected in policy['files'].items():
    path = root / name
    if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
      raise RuntimeError('Model submission guard source/artifact changed: ' + name)


def _library(name):
  path = Path(__file__).with_name(name)
  if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != _GUARD_HASHES[name]:
    raise RuntimeError('Model submission guard artifact changed: ' + name)
  return path


def selected_legacy():
  return _selection is not None


def _guard(chestnut):
  global _protection
  if _selection is None:
    raise RuntimeError('Select the model runtime before loading a device artifact')
  if _selection.get('purpose') == 'compiler':
    raise RuntimeError('A model compiler cannot load inference artifacts')
  if chestnut and _selection['role'] != 'driving':
    raise ValueError('Driver monitoring requires the QCOM runtime')
  if _protection is None:
    _verify_policy()
    # Driving can load its verified QCOM fallback before attempting Chestnut.
    if _selection['role'] == 'driving':
      from openpilot.starpilot.models.runtime_bridge.usb import USBProtection
      candidate = USBProtection(_library('libbounded_wait.so'), _library('libusb_guards.so'))
      candidate.install_fresh_guard()
    else:
      from openpilot.starpilot.models.runtime_bridge.qcom import Protection
      from tinygrad.runtime.support import hcq2
      from tinygrad.uop.ops import Ops, ProgramInfo
      candidate = Protection(_library('libbounded_wait.so'))
      original = hcq2.lower_and_compile
      def checked(linear):
        if any(u.op is Ops.CALL and (u.body.op is Ops.SINK or
               (u.body.op is Ops.PROGRAM and not (isinstance(u.body.arg, ProgramInfo) and
                u.body.src and u.body.src[-1].op is Ops.BINARY))) for u in linear.toposort()):
          raise ValueError('Unexpected fresh monitoring submission compilation')
        return original(linear)
      hcq2.lower_and_compile = checked
    _protection = candidate
  return _protection


_STOCK_SHA256 = {
  'dmonitoring_model_tinygrad.pkl': '7f7198c63d2d9b0d015cc860fdd836db50a4b9a75ab5d56cffd4d4eee5eb7b97',
  'dm_warp_1928x1208_tinygrad.pkl': '5711934a11792e539e72ce68837b8bab802ee7bd2a909402fd35a4cc4efc382f',
  'dm_warp_1344x760_tinygrad.pkl': '79df4a2f9701aea9cf6c21477cae07852d7d8c245737599e6b72a1e6fa4fe88f',
}


def _stock_bytes(path):
  import os
  import stat
  path = Path(path)
  expected = _STOCK_SHA256.get(path.name.removesuffix('.unchunked'))
  if expected is None:
    raise ValueError('Unqualified stock model artifact')
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
  with os.fdopen(fd, 'rb') as source:
    before = os.fstat(source.fileno())
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= 20_768_359:
      raise ValueError('Unexpected stock artifact file')
    data = source.read(20_768_360)
    after = os.fstat(source.fileno())
  def identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns
  if (identity(before) != identity(after) or len(data) != before.st_size or hashlib.sha256(data).hexdigest() != expected):
    raise ValueError('Stock model artifact changed')
  return data


def _load_monitoring(data):
  # The bounded stock artifact is already authenticated. Consume those exact bytes;
  # the DISK loader reopens paths and requests writable mmap, so it cannot use sealed files.
  import io
  import pickle
  import struct
  from tinygrad import Device
  from tinygrad.device import Buffer
  from tinygrad.dtype import dtypes
  if len(data) < 8:
    raise ValueError('Missing monitoring pickle envelope')
  opcode_size = struct.unpack('<q', data[:8])[0]
  if not 0 < opcode_size <= len(data) - 8:
    raise ValueError('Invalid monitoring pickle envelope')
  end = 8 + opcode_size
  if end == len(data):
    return pickle.loads(data[8:end])
  arena = Buffer(Device.DEFAULT, len(data) - end, dtypes.uchar, initial_value=data[end:])
  unpickler = pickle.Unpickler(io.BytesIO(data[8:end]))
  unpickler.persistent_load = lambda record: arena.view(*record)
  return unpickler.load()


def load_oob(path, chestnut=False):
  if _selection is None:
    raise RuntimeError('A device model loader requires the selected runtime')
  if _selection.get('purpose') == 'compiler':
    raise RuntimeError('A model compiler cannot load inference artifacts')
  monitoring = _selection['role'] == 'monitoring'
  authenticated = _stock_bytes(path) if monitoring else None
  from tinygrad import Context, Device
  from tinygrad.runtime.ops_qcom import QCOMDevice
  if not isinstance(Device['QCOM'], QCOMDevice):
    raise RuntimeError('Expected the native QCOM device')
  from tinygrad_repo.examples.openpilot.helpers import load_pickle
  protection = _guard(chestnut)
  with Context(DEV='USB+AMD:LLVM' if chestnut else 'QCOM'):
    artifact = _load_monitoring(authenticated) if monitoring else load_pickle(path, out_of_band=True)
  if isinstance(artifact, dict) and artifact.get('artifact_abi') == 'tinygrad_single_v1_arena':
    if chestnut:
      return protection.artifact(artifact)
    from openpilot.starpilot.models.runtime_bridge.qcom import Protection
    return Protection.artifact(protection, artifact)
  if _selection['role'] != 'monitoring':
    raise ValueError('Unqualified stock driving artifact for the selected runtime')
  from openpilot.starpilot.models.runtime_bridge.capture import protect_capture
  captures = [value for value in artifact.values() if getattr(value, 'captured', None) is not None]
  if len(captures) != 1 or artifact.get('run') is not captures[0]:
    raise ValueError('Unexpected monitoring capture layout')
  protect_capture(captures[0], protection)
  return artifact


def load_warp(path):
  import pickle
  if _selection is None or _selection['role'] != 'monitoring':
    raise RuntimeError('A monitoring warp loader requires the selected runtime')
  if _selection.get('purpose') == 'compiler':
    raise RuntimeError('A model compiler cannot load inference artifacts')
  from openpilot.starpilot.models.runtime_bridge.capture import protect_capture
  protection = _guard(False)
  data = _stock_bytes(path)
  artifact = pickle.loads(data)
  if not isinstance(artifact, dict) or set(artifact) != {'metadata', 'run', 'input_specs'}:
    raise ValueError('Unexpected monitoring warp layout')
  return protect_capture(artifact['run'], protection)
