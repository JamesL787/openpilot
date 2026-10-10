"""
Jetlink on this fork: the one module that holds every openpilot import Jetlink needs, and the functions the hooks call.

Jetlink (starpilot/third_party/jetlink_repo, see VENDORED.md there) runs a large driving model on an attached Jetson,
Mac or iPhone over USB and never imports openpilot. It defines what it needs as an interface
(jetlink.openpilot.interface.Openpilot); Adapter below implements it. The hooks in manager, modeld, hardwared, selfdrived
and the UI call the functions at the bottom, which answer as if the link were off when Jetlink is not vendored, speaks
another API, or fails.

Derived from Zoompilot's adapter (MIT, 02be6b631d06), reworked for this fork's Params, model manager, modeld and
engagement state. What differs on purpose:

* Params.put has no ``block`` keyword; the adapter's blocking contract is put() vs put_nonblocking().
* The model manager's big-model slot is a model-key STRING for Chestnut artifacts, not Jetlink's {ref, displayName}
  JSON, and its manifest is not Jetlink's {bundles} catalog. Phase 1 therefore gives Jetlink no slot and no catalog
  (Keys.big_model / Keys.catalog are None) and runs Jetlink's pinned default model; validate_spec() refuses anything else.
* make_warp() passes this fork's explicit frame_skip / image-history arguments to compile_modeld.make_warp.
* Chestnut is not Jetlink's business: Jetlink stays off while one is fitted (native path unchanged).

The resident owner (jetlinkd) imports this module in a long-lived process, so the top level is the standard library
only; everything else is imported where it is used. tests/test_adapter.py holds the line.
"""
from __future__ import annotations

import functools
import os
import sys
import threading
from collections import namedtuple
from pathlib import Path

# the version of jetlink.openpilot's API this adapter is written to; any other is treated as Jetlink being absent,
# with the reason as the offroad alert
API = 2

# the gadget owner, as manager names the process and selfdrived exempts it
OWNER = 'jetlinkd'

# the module Jetlink's own processes (the provisioning run, the warp build) import to reach this adapter. Written out
# rather than __name__ so it resolves the same whichever way manager imported this file
ADAPTER_MODULE = 'openpilot.starpilot.jetlink_adapter'

# the Jetlink setting, stored as an index into MODES (jetlink.openpilot.MODES, written out so the settings UI builds
# the control without importing Jetlink)
MODES = ('off', 'usb', 'ios')

# the modes this build offers: a Jetson or Mac on the cable ('usb') and an iPhone or iPad on it ('ios', the phone's own
# Jetlink app serves the model). The iOS transport is Jetlink's own, vendored unchanged; it has not been bench-tested on
# this fork's hardware the way USB has (see docs/JETLINK.md)
SUPPORTED_MODES = ('off', 'usb', 'ios')

# the params Jetlink reads and writes, all declared in params_keys.h. big_model and catalog stay None in phase 1: the
# fork's ActiveBigModel is a model-key string and its manifest is not Jetlink's catalog, so Jetlink runs its pinned
# default model (see README "Model identity")
_Keys = namedtuple('_Keys', 'link offroad progress spec pointers big_model catalog charge_phone')
KEYS = _Keys(link='JetlinkLink', offroad='IsOffroad', progress='JetlinkProgress', spec='JetlinkSpec',
             pointers='JetlinkModelPointers', big_model='JetlinkBigModel', catalog='JetlinkCatalog',
             charge_phone='JetlinkChargePhone')

# comma's Chestnut, running and in its ROM (system.hardware.usb). The USB-C port hosts one and is never held as a Jetlink
# device beside it. The hardware module is light, but the owner must not import it; a test pins this copy to it
CHESTNUT_IDS = frozenset({(0xADD1, 0x0001), (0x3801, 0x0001), (0x174C, 0x2464), (0x174C, 0x2463)})

_HERE = Path(__file__).resolve().parent

# Jetlink as vendored: package at jetlink/, root helper at scripts/comma/ (jetlink.comma.root resolves it relative to
# the package, so the layout is upstream's)
VENDOR_DIR = _HERE.parent / 'third_party' / 'jetlink_repo'

# where the build puts the warp for each camera (SConscript) and modeld loads it from: in this fork's tree, never in
# the vendored package, committed beside the other prebuilt pickles (see .gitignore). Not Paths.comma_home(), which on
# AGNOS is a tmpfs overlay
WARP_DIR = _HERE / 'models'

OWNER_LOG = Path('/data/log/jetlink-owner.log')

_AGNOS = os.path.isfile('/AGNOS')


def vendor_on_path() -> None:
  """Make ``import jetlink`` find the vendored package. Last on the path, so nothing in it shadows a module of the
  fork's own; idempotent. launch_chffrplus.sh puts starpilot/third_party on PYTHONPATH, but the package lives one level
  down so that it keeps upstream's layout, and every process that reaches Jetlink comes through here."""
  path = str(VENDOR_DIR)
  if path not in sys.path and VENDOR_DIR.is_dir():
    sys.path.append(path)


def pythonpath(basedir: str) -> str:
  """PYTHONPATH for the processes Jetlink starts (the provisioning run, the warp build)."""
  parts = [basedir, str(VENDOR_DIR)]
  parts += [p for p in os.environ.get('PYTHONPATH', '').split(os.pathsep) if p and p not in parts]
  return os.pathsep.join(parts)


def _params_dir() -> Path:
  """The params store's directory, by params.cc and hw.h's rule: PARAMS_ROOT, else /data/params on a device and
  ~/.comma<OPENPILOT_PREFIX>/params elsewhere, then /<OPENPILOT_PREFIX, or d>. Per call, so it follows a prefix as Params
  does; the environment only, so it never raises."""
  prefix = os.environ.get('OPENPILOT_PREFIX', '')
  root = os.environ.get('PARAMS_ROOT')
  if root is None:
    root = '/data/params' if _AGNOS else os.path.join(os.environ.get('HOME', ''), '.comma' + prefix, 'params')
  # params.cc: the subdirectory is OPENPILOT_PREFIX, or d when it is unset (set but empty means none)
  return Path(root) / os.environ.get('OPENPILOT_PREFIX', 'd')


def warp_path(cam_w: int, cam_h: int, model_w: int, model_h: int) -> Path:
  """The warp for one geometry: the build's target and what modeld opens."""
  return WARP_DIR / f'warp_{cam_w}x{cam_h}_{model_w}x{model_h}_tinygrad.pkl'


def tinygrad_commit() -> str:
  """The tinygrad this tree runs: the pin declared in tinygrad_repo/TINYGRAD_COMMIT (compile_modeld reads the same file)."""
  return (_HERE.parents[1] / 'tinygrad_repo' / 'TINYGRAD_COMMIT').read_text().strip()


def jetlink_version() -> str:
  """The vendored package's version, read as text so the owner never imports it for this."""
  for line in (VENDOR_DIR / 'jetlink' / '__init__.py').read_text().splitlines():
    if line.startswith('__version__'):
      return line.partition('=')[2].strip().strip("'\"")
  return ''


def warp_meta_path(path: Path) -> Path:
  return path.with_name(path.name + '.json')


def warp_meta(cam_w: int, cam_h: int, model_w: int, model_h: int) -> dict:
  """What a warp pickle was built against, written beside it by the build. A pickle is only as good as the tinygrad that
  captured it: a matching call convention does not prove the kernels and buffer layout still agree."""
  return {'tinygrad_commit': tinygrad_commit(), 'jetlink_version': jetlink_version(), 'camera': [cam_w, cam_h],
          'model': [model_w, model_h], 'api': API}


def warp_problem(cam_w: int, cam_h: int, model_w: int, model_h: int) -> str | None:
  """Why the warp on disk for this geometry cannot be used, or None when it can. A missing pickle is not a "problem" here
  (Jetlink says so itself); a pickle built against another tinygrad or Jetlink, or with no record of what it was built
  against, is refused rather than trusted."""
  import json
  path = warp_path(cam_w, cam_h, model_w, model_h)
  if not path.is_file():
    return None
  try:
    meta = json.loads(warp_meta_path(path).read_text())
  except (OSError, ValueError):
    return "the warp has no build record; rebuild it with starpilot/jetlink_adapter/build_warp.py"
  want = warp_meta(cam_w, cam_h, model_w, model_h)
  for key in ('tinygrad_commit', 'jetlink_version', 'camera', 'model', 'api'):
    if meta.get(key) != want[key]:
      return f"the warp was built with {key} {meta.get(key)}, this build has {want[key]}; rebuild it with build_warp.py"
  return None


def stored_mode() -> str:
  """The Jetlink setting as stored, one of MODES, off the params file (never raises): the same read Jetlink's own
  readers make, for the checks that must not wait for Jetlink to import."""
  try:
    index = int((_params_dir() / KEYS.link).read_bytes())
  except (OSError, ValueError):
    return 'off'
  return MODES[index] if 0 <= index < len(MODES) else 'off'


def _wanted() -> bool:
  """The link is set to a mode this build offers, and not off. The cheap first test of every hook: with the link off,
  Jetlink is never imported by manager, hardwared, modeld or the UI."""
  mode = stored_mode()
  return mode != 'off' and mode in SUPPORTED_MODES


def holds_usb_port() -> bool:
  """Does the link want the comma's USB-C port? ADB's gadget holds the only device controller and Jetlink refuses to
  share it, so while this is true the UI keeps ADB off. Files only, like _wanted."""
  return _wanted()


def effective_catalog(raw) -> dict:
  """The catalog Jetlink and the picker see: whatever was fetched, plus every model this fork has validated.

  Jetlink takes its default model from the catalog (`Models.default_model`), and a comma that has never been online has no
  catalog: without this the link would wait for a catalog forever and never join. Adding the validated models makes the
  pinned default available offline, and keeps it available when a fetched catalog no longer lists it. The injected entries
  carry the selector version Jetlink filters on."""
  from jetlink.registry.catalog import REQUIRED_SELECTOR_VERSION
  from openpilot.starpilot.jetlink_adapter.profiles import PROFILES
  catalog = dict(raw) if isinstance(raw, dict) else {}
  bundles = [b for b in catalog.get('bundles', []) if isinstance(b, dict)]
  listed = {b.get('ref') for b in bundles}
  for p in PROFILES.values():
    if p.ref not in listed:
      bundles.append({'ref': p.ref, 'display_name': f"{p.name} Model", 'index': 0, 'minimum_selector_version': REQUIRED_SELECTOR_VERSION})
  catalog['bundles'] = bundles
  return catalog


def owner_config():
  """What jetlinkd needs: data only, so the owner imports nothing heavy."""
  vendor_on_path()
  from jetlink.openpilot.interface import Keys, OwnerConfig

  from openpilot.common.basedir import BASEDIR
  return OwnerConfig(params_dir=_params_dir(), keys=Keys(**KEYS._asdict()), chestnut_ids=CHESTNUT_IDS,
                     adapter=ADAPTER_MODULE, cwd=Path(BASEDIR), env={'PYTHONPATH': pythonpath(BASEDIR)}, log_file=OWNER_LOG)


def main() -> None:
  """jetlinkd: hold the USB gadget until manager stops this process."""
  vendor_on_path()
  from jetlink.openpilot.owner import main as run_owner
  run_owner(owner_config())


def adapter() -> Adapter:
  """The adapter, for Jetlink's entry points that run as their own process: the provisioning run and the warp build."""
  vendor_on_path()
  return Adapter()


class Adapter:
  """jetlink.openpilot.interface.Openpilot over this fork."""

  def __init__(self):
    from jetlink.openpilot.interface import Keys

    from openpilot.common.basedir import BASEDIR
    from openpilot.common.swaglog import cloudlog
    self.keys = Keys(**KEYS._asdict())
    self.log = cloudlog
    self.basedir = Path(BASEDIR)
    # one Params per store: constructing one costs 144 us on the comma against 110 us for the read, and the UI reads
    # several five times a second. By store, since a test or a bench runs under its own prefix
    self._stores: dict[Path, object] = {}

  # -- params ---------------------------------------------------------------

  def params_dir(self) -> Path:
    return _params_dir()

  def _params(self):
    where = _params_dir()
    store = self._stores.get(where)
    if store is None:
      from openpilot.common.params import Params
      store = self._stores[where] = Params()
    return store

  def get(self, key: str):
    # read from hardwared and the UI's threads, which an unknown key (a params library older than the key) must not
    # take down. Params.get already decodes by the declared type (INT -> int, JSON -> dict)
    try:
      value = self._params().get(key)
    except Exception:
      value = None
    if key == KEYS.catalog:
      value = effective_catalog(value)
    return value

  def put(self, key: str, value, *, block: bool = False) -> None:
    # Params.put blocks until the value is on disk and has no ``block`` keyword; the nonblocking form is the one that
    # does not. A caller that reads the value straight back (Models.resolve_pointer) asks for block=True
    params = self._params()
    if block:
      params.put(key, value)
    else:
      params.put_nonblocking(key, value)

  def remove(self, key: str) -> None:
    self._params().remove(key)

  # -- the device -------------------------------------------------------------

  def chestnut_present(self) -> bool:
    # sysfs, not libusb: includes the bootloader ids, which Jetlink must not claim the port from either
    from openpilot.system.hardware.usb import is_chestnut_usb_id, read_int, usb_devices
    return any(is_chestnut_usb_id(read_int(d / "idVendor", 16), read_int(d / "idProduct", 16), include_bootloader=True)
               for d in usb_devices())

  def camera(self) -> tuple[int, int, int, int]:
    """(cam_w, cam_h, model_w, model_h) for this device: the stream modeld connects to, the same choice
    selfdrive/modeld makes for its own artifacts (1928x1208 on tici, 1344x760 on mici)."""
    from openpilot.common.transformations.camera import _ar_ox_fisheye, _os_fisheye
    from openpilot.common.transformations.model import MEDMODEL_INPUT_SIZE
    from openpilot.system.hardware import HARDWARE
    camera = _os_fisheye if HARDWARE.get_device_type() == "mici" else _ar_ox_fisheye
    return camera.width, camera.height, *MEDMODEL_INPUT_SIZE

  def warp_path(self, cam_w: int, cam_h: int, model_w: int, model_h: int) -> Path:
    """Where Jetlink looks for the warp, for reading. A pickle that fails warp_problem() is reported as absent (the
    path with a ``.stale`` suffix, which does not exist), so Jetlink's own checks (`built()`, `load()`) refuse it with its
    usual "no warp built" and the driver sees the specific reason through reason(). The build writes to warp_path()."""
    try:
      if warp_problem(cam_w, cam_h, model_w, model_h) is not None:
        return warp_path(cam_w, cam_h, model_w, model_h).with_suffix('.pkl.stale')
    except Exception:
      return warp_path(cam_w, cam_h, model_w, model_h).with_suffix('.pkl.stale')
    return warp_path(cam_w, cam_h, model_w, model_h)

  def model_root(self) -> Path:
    # the model manager's root. Jetlink keeps its ONNX downloads in a directory of its own below it (jetlink/):
    # ModelManager only ever deletes top-level *driving artifact files*, so a directory is outside its reach
    from openpilot.starpilot.common.starpilot_variables import MODELS_PATH
    return Path(MODELS_PATH)

  @property
  def catalog_selector(self) -> int:
    # the catalog is Jetlink's own fetch, kept at the selector version it merges to
    from jetlink.registry.catalog import REQUIRED_SELECTOR_VERSION
    return REQUIRED_SELECTOR_VERSION

  # -- modeld -----------------------------------------------------------------

  def model_face(self):
    """What Jetlink's large-model state carries for modeld. This fork's modeld does not read it back (the runner seam
    in runner.py owns generation flags and the action function), but Jetlink requires it and the parser is the one that
    matters: the same Parser the local supercombo path uses."""
    from jetlink.openpilot.interface import ModelFace

    from openpilot.selfdrive.modeld.constants import ModelConstants
    from openpilot.selfdrive.modeld.modeld import LAT_SMOOTH_SECONDS, LONG_SMOOTH_SECONDS, get_action_from_model
    from openpilot.selfdrive.modeld.parse_model_outputs import Parser
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    return ModelFace(parser=Parser, frame_size=lambda w, h: get_nv12_info(w, h)[3], desire_len=ModelConstants.DESIRE_LEN,
                     constants=ModelConstants, lat_smooth_seconds=LAT_SMOOTH_SECONDS,
                     long_smooth_seconds=LONG_SMOOTH_SECONDS, get_action_from_model=get_action_from_model)

  def event(self, name: str, **fields) -> None:
    self.log.event(name, **fields)

  def validate_spec(self, spec) -> None:
    """Refuse a server model this fork has not validated. Called by the vendored joining state before it builds the
    large model (the one local modification to the vendored package, see VENDORED.md); raising keeps the small model
    driving and backs the join off, with the reason in the log."""
    from openpilot.starpilot.jetlink_adapter.profiles import require_profile
    require_profile(spec)

  # -- the build --------------------------------------------------------------

  def make_warp(self, cam_w: int, cam_h: int, model_w: int, model_h: int):
    """The camera warp graph for this geometry and the size of the NV12 frame it reads.

    The policy-history graph (image history lives in the model, not the warp): warp(tfm, big_tfm, frame, big_frame) ->
    uint8 (2, 6, model_h/2, model_w/2), the (2, 6, 128, 256) Jetlink sends. frame_skip only shapes the warp-history
    variant, so it is pinned to 1 here; the policy-history graph ignores it."""
    # compile_modeld first: it patches tinygrad's firmware fetch as it loads
    from openpilot.selfdrive.modeld.compile_modeld import IMAGE_HISTORY_IN_POLICY, NV12Frame, make_warp
    from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
    nv12 = NV12Frame(cam_w, cam_h, *get_nv12_info(cam_w, cam_h))
    return make_warp(nv12, model_w, model_h, 1, image_history_pipeline=IMAGE_HISTORY_IN_POLICY), nv12.size


# -- what the hooks call ------------------------------------------------------

class _Absent:
  """Jetlink's answers when it cannot run here: not vendored (why is None), or a package this build cannot use (why
  says so, as the offroad alert, to someone who turned the link on)."""

  def __init__(self, why: str | None):
    self.why = why

  def enabled(self) -> bool:
    return False

  def status(self):
    return None

  def reason(self) -> str | None:
    if self.why is None:
      return None
    # the setting as Jetlink reads it, a file: hardwared asks twice a second
    try:
      on = 0 < int((_params_dir() / KEYS.link).read_bytes()) < len(MODES)
    except (OSError, ValueError):
      on = False
    return self.why if on else None

  def prepare(self) -> bool:
    return False

  def attach(self, small, cam_w: int, cam_h: int):
    return None

  def request_shutdown(self, reason: str = '') -> bool:
    return False

  def shutdown_pending(self) -> bool:
    return False

  def should_extend_catalog(self) -> bool:
    return False

  def extend_catalog(self, catalog: dict) -> dict:
    return catalog

  def model_state(self, ref: str) -> str | None:
    return None


_bound = None
_binding = threading.Lock()


def _api():
  """Jetlink for this process, bound to the adapter on first use. Kept, the null answers included: Python does not cache
  a failed import, and searching the path again on every UI and hardwared call costs more than the call. One per process:
  prepare() and attach() have to reach the same one."""
  global _bound
  if _bound is None:
    with _binding:
      if _bound is None:
        _bound = _bind()
  return _bound


def _bind():
  vendor_on_path()
  try:
    import jetlink
    if getattr(jetlink, '__file__', None) is None:
      return _Absent(None)   # an empty directory, which Python takes for a namespace package
    import jetlink.openpilot as jl
  except ModuleNotFoundError as e:
    if e.name == 'jetlink':
      return _Absent(None)   # not vendored: the link does not exist on this build
    if (e.name or '').startswith('jetlink.'):
      return _unusable("jetlink package too old for this build", e)
    return _unusable(f"jetlink failed to load: {e}", e)
  except Exception as e:
    return _unusable(f"jetlink failed to load: {type(e).__name__}: {e}", e)
  api = getattr(jl, 'API', None)
  if api != API:
    return _unusable(f"jetlink package API {api}, this build expects {API}")
  try:
    return jl.bind(Adapter())
  except Exception as e:
    return _unusable(f"jetlink failed to start: {type(e).__name__}: {e}", e)


def _unusable(why: str, error: Exception | None = None) -> _Absent:
  _log_failure(why, error)
  return _Absent(why)


# manager, hardwared, selfdrived, the UI and modeld call in here on every device, link on or off: whatever Jetlink does
# wrong turns the link off and is logged, and never takes one of them down. Jetlink's own readers never raise; this is the
# net under that promise. Hook -> the failure last logged for it, cleared by a call that works
_failed_hooks: dict[str, str] = {}


def _log_failure(what: str, error: Exception | None) -> None:
  try:
    from openpilot.common.swaglog import cloudlog
    cloudlog.error("jetlink: %s", what, exc_info=error)
  except Exception:
    pass


def _guarded(default):
  def wrap(hook):
    @functools.wraps(hook)
    def call(*args, **kwargs):
      try:
        result = hook(*args, **kwargs)
      except Exception as e:
        # once per distinct error: the UI would log a failing status five times a second
        error = f"{type(e).__name__}: {e}"
        if _failed_hooks.get(hook.__name__) != error:
          _failed_hooks[hook.__name__] = error
          _log_failure(f"{hook.__name__}() failed", e)
        return default(*args, **kwargs) if callable(default) else default
      _failed_hooks.pop(hook.__name__, None)
      return result
    return call
  return wrap


@_guarded(False)
def should_run(started: bool, params, CP, starpilot_toggles=None) -> bool:
  """manager's rule for jetlinkd: the link is on and no Chestnut is fitted. jetlinkd runs onroad too: a gadget whose
  owner exits leaves the bus."""
  return _wanted() and _api().enabled()


@_guarded(None)
def status():
  """One snapshot for the UI and the panels (jetlink.openpilot.Status), or None when there is no Jetlink here."""
  return _api().status()


# Jetlink's reasons that the driver can act on, with what to do. Anything else is shown as Jetlink words it
_ADVICE = {
  "no warp built for this camera": "no warp was built for this camera; update or reinstall, or turn Jetlink off",
}


_status_cache: tuple[float, object] = (0.0, None)


def status_cached(ttl: float = 0.5):
  """status(), at most once per `ttl` seconds: the settings UI asks on every frame, and a snapshot reads several files."""
  global _status_cache
  import time
  now = time.monotonic()
  stamp, value = _status_cache
  if now - stamp >= ttl:
    value = status()
    _status_cache = (now, value)
  return value


@_guarded(None)
def reason() -> str | None:
  """Why the link the user turned on cannot run: hardwared's offroad alert, worded for the driver. Files only, so
  hardwared can ask twice a second. None with the link off."""
  mode = stored_mode()
  if mode == 'off':
    return None   # a device with the link off is never nagged, and never imports Jetlink for it
  if mode not in SUPPORTED_MODES:
    return f"{mode} mode is not supported on this build; set Jetlink to USB or off"
  pick = _params_store().get(KEYS.big_model)
  ref = pick.get('ref') if isinstance(pick, dict) else None
  if ref and ref not in supported_refs():
    return "the selected Jetlink model has not been validated on this fork; pick the default in the model manager"
  why = _api().reason()
  if why == "no warp built for this camera":
    # a pickle that exists but cannot be trusted is a different instruction from one that was never built
    try:
      cam_w, cam_h, model_w, model_h = Adapter().camera()
      stale = warp_problem(cam_w, cam_h, model_w, model_h)
    except Exception:
      stale = None
    if stale:
      return stale
  return _ADVICE.get(why, why) if why else why


@_guarded(False)
def prepare() -> bool:
  """modeld, before config_realtime_process: will the link join this modeld? The GPU's setup has to happen now, or its
  threads inherit the frame loop's realtime priority and core."""
  return _wanted() and _api().prepare()


# what in_control() reads; modeld subscribes to all three
IN_CONTROL = ('carState', 'carControl', 'starpilotCarState')


@_guarded(True)
def in_control(sm, aol_possible: bool = True) -> bool:
  """modeld, before every frame: is anything in control of the car, or about to be? The large model swaps in only while
  the answer is False.

  True (the conservative answer) when:
  * any of carState, carControl or starpilotCarState is late or invalid, so a card that died cannot leave a swap landing
    on stale controls;
  * openpilot is engaged (carControl.enabled) or actually steering/accelerating (latActive / longActive);
  * always-on lateral (AOL) is enabled; or
  * AOL is armed but momentarily paused (brake, blinker, calibration, a stop): `alwaysOnLateralAllowed` stays set while
    `alwaysOnLateralEnabled` drops, and it steers again by itself the moment the condition clears. `latActive == False` alone
    is therefore not permission to change the model. `aol_possible` is whether this car can run AOL at all (the
    StarPilotCarParams flag); where it cannot, `allowed` can be set by a main-cruise toggle without ever steering and must
    not block the swap forever."""
  if not (sm.all_alive(IN_CONTROL) and sm.all_valid(IN_CONTROL)):
    return True
  cc, fp = sm['carControl'], sm['starpilotCarState']
  if cc.enabled or cc.latActive or cc.longActive:
    return True
  if fp.alwaysOnLateralEnabled:
    return True
  return bool(aol_possible and fp.alwaysOnLateralAllowed)


@_guarded(None)
def attach(small, cam_w: int, cam_h: int):
  """modeld, once the camera is up and `small` is built: the model to run, `small` driving until the link has joined;
  None unless prepare() said yes. `small` must be the local runner facade (runner.LocalRunner), not a raw ModelState."""
  return _api().attach(small, cam_w, cam_h)


@_guarded(False)
def request_shutdown(reason: str = '') -> bool:
  """manager, once, when the comma is about to power off for good: ask for the far end to go down with it. Returns at
  once: True when the request now waits for jetlinkd, which shutdown_pending() follows."""
  return _api().request_shutdown(reason)


@_guarded(False)
def shutdown_pending() -> bool:
  """manager, every loop after request_shutdown(): has jetlinkd still to take the request? A stat."""
  return _api().shutdown_pending()


@_guarded(None)
def model_state(ref: str) -> str | None:
  """A catalog model's state for the picker: 'ready' (built on the host), 'downloaded' (on the comma) or None."""
  return _api().model_state(ref)


@_guarded(False)
def should_extend_catalog() -> bool:
  """Should the catalog carry the models newer catalogs list? Hardware, not the link setting; never beside a Chestnut."""
  return _api().should_extend_catalog()


@_guarded(lambda catalog: catalog)
def extend_catalog(catalog: dict) -> dict:
  """The catalog with the models newer catalogs list folded in."""
  return _api().extend_catalog(catalog)


# -- the model picker ----------------------------------------------------------
# Jetlink can run any model in its catalog; this fork runs the ones profiles.py has validated. The picker lists the catalog,
# marks which are validated, and refuses a pick that is not, so a pick can never be one the join would then refuse.

_store = None


def _params_store():
  """One adapter for the picker's reads and writes, created on first use (the module top level stays stdlib only)."""
  global _store
  if _store is None:
    vendor_on_path()
    _store = Adapter()
  return _store


def supported_refs() -> frozenset:
  from openpilot.starpilot.jetlink_adapter.profiles import PROFILES
  return frozenset(p.ref for p in PROFILES.values())


@_guarded(False)
def refresh_catalog() -> bool:
  """The model manager's refresh: fetch the big-model catalogs and keep them in KEYS.catalog. Network; a failed fetch keeps
  the last catalog (Jetlink's big_catalog never raises). Skipped beside a Chestnut. True when the stored catalog changed."""
  # only for someone who turned the link on: the fetch is network traffic nobody else asked for. The picker lists the last
  # catalog fetched either way
  if not _wanted() or not should_extend_catalog():
    return False
  store = _params_store()
  stored = store._params().get(KEYS.catalog)       # raw: what was fetched, without the validated models effective_catalog adds
  stored = stored if isinstance(stored, dict) else {}
  merged = extend_catalog(stored)
  if not merged.get('bundles') or merged == stored:
    return False
  store.put(KEYS.catalog, merged, block=True)
  return True


def _wanted_for_picker() -> bool:
  """The picker exists when the feature does (Jetlink vendored) and the setting is not a mode this build refuses; the link
  itself may be off, since the catalog is worth having before it is turned on."""
  return VENDOR_DIR.is_dir() and stored_mode() in SUPPORTED_MODES


@_guarded(list)
def models() -> list:
  """The picker's rows, newest first: {ref, name, state, selected, supported}. `supported` is whether profiles.py has validated
  the model; `state` is 'ready' (built on the host), 'downloaded' (on the comma) or None. Records only, no network."""
  if not _wanted_for_picker():
    return []
  from jetlink.registry.catalog import REQUIRED_SELECTOR_VERSION, is_ref
  store = _params_store()
  catalog = store.get(KEYS.catalog)
  bundles = catalog.get('bundles', []) if isinstance(catalog, dict) else []
  pick = store.get(KEYS.big_model)
  picked = pick.get('ref') if isinstance(pick, dict) else None
  ok = supported_refs()
  rows = []
  for b in sorted((b for b in bundles if isinstance(b, dict)), key=lambda b: int(b.get('index', 0) or 0), reverse=True):
    ref = b.get('ref')
    try:
      selector = int(b.get('minimum_selector_version', 0))
    except (TypeError, ValueError):
      continue
    if not is_ref(ref) or selector != REQUIRED_SELECTOR_VERSION or any(r['ref'] == ref for r in rows):
      continue
    rows.append({'ref': ref, 'name': str(b.get('display_name') or ref[:10]), 'state': model_state(ref),
                 'selected': ref == picked, 'supported': ref in ok})
  return rows


@_guarded((False, "Jetlink is not available on this build"))
def select_model(ref: str | None) -> tuple:
  """Pick the big model Jetlink runs, by catalog ref; None or '' goes back to Jetlink's pinned default. Returns (ok, message).
  Refuses a ref the catalog does not list, and one this fork has not validated (profiles.py), with the reason."""
  if not _wanted_for_picker():
    return False, "Jetlink is not available on this build"
  store = _params_store()
  if not ref:
    store.remove(KEYS.big_model)
    return True, ""
  row = next((m for m in models() if m['ref'] == ref), None)
  if row is None:
    return False, f"Unknown Jetlink model {ref[:10]}"
  if not row['supported']:
    return False, f"{row['name']} has not been validated on this fork; only validated models can be picked"
  store.put(KEYS.big_model, {'ref': ref, 'displayName': row['name']}, block=True)
  return True, ""
