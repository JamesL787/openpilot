"""The adapter against Jetlink's interface, the fork's Params, and the ways Jetlink can be absent or wrong."""
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from openpilot.common.params import Params
from openpilot.starpilot import jetlink_adapter as ja

REPO = Path(__file__).resolve().parents[3]
PARAMS_KEYS = (REPO / "common" / "params_keys.h").read_text()


def declared(key: str) -> str:
  """The type params_keys.h declares for `key`."""
  line = next(line for line in PARAMS_KEYS.splitlines() if f'{{"{key}",' in line)
  return next(t for t in ("BOOL", "INT", "FLOAT", "JSON", "STRING", "BYTES", "TIME") if f", {t}" in line)


class TestTheInterface:
  def test_the_adapter_implements_all_of_it(self):
    from jetlink.openpilot.interface import Openpilot, conformance
    assert conformance(ja.Adapter(), Openpilot) == []

  def test_api_modes_and_states_are_jetlinks(self):
    import jetlink.openpilot as jl
    assert ja.API == jl.API == 2
    assert ja.MODES == jl.MODES
    assert set(ja.SUPPORTED_MODES) <= set(ja.MODES)

  def test_accelerator_states_in_the_schema_are_jetlinks(self):
    """modeld publishes joining.big_model_state by name into the schema's enum."""
    import jetlink.openpilot as jl
    from cereal import custom
    enumerants = custom.StarPilotModelDataV2.AcceleratorState.schema.enumerants
    assert [name for name, _ in sorted(enumerants.items(), key=lambda kv: kv[1])] == list(jl.STATES)

  def test_backends_in_the_schema_are_the_ones_the_runner_publishes(self):
    from cereal import custom
    from openpilot.starpilot.jetlink_adapter import runner
    names = set(custom.StarPilotModelDataV2.Backend.schema.enumerants)
    assert {runner.LOCAL, runner.JETLINK} <= names

  def test_the_adapter_module_is_importable_by_the_name_jetlinks_processes_use(self):
    import importlib
    module = importlib.import_module(ja.ADAPTER_MODULE)
    assert module.adapter and module.owner_config and module.main

  def test_the_owners_path_stays_light(self):
    """jetlinkd stays resident for the drive: importing the adapter and building its config pulls in no numpy, capnp, zmq
    or tinygrad."""
    code = "; ".join(["import sys", "from openpilot.starpilot import jetlink_adapter as ja", "cfg = ja.owner_config()",
                      "heavy = [m for m in ('numpy', 'capnp', 'zmq', 'tinygrad', 'cereal') if m in sys.modules]",
                      "print('HEAVY', heavy)"])
    env = {**os.environ, "PYTHONPATH": ja.pythonpath(str(REPO))}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=REPO)
    heavy_line = next(line for line in out.stdout.splitlines() if line.startswith("HEAVY"))
    # openpilot.common.basedir is os.path only; swaglog is imported by Adapter(), not by owner_config()
    assert heavy_line == "HEAVY []", out.stderr[-500:]

  def test_the_chestnut_ids_are_the_hardware_modules(self):
    from openpilot.system.hardware import usb
    assert ja.CHESTNUT_IDS == frozenset(usb.CHESTNUT_USB_IDS + usb.CHESTNUT_ROM_USB_IDS)

  def test_a_chestnut_is_found_by_its_usb_ids_including_the_bootloader(self, monkeypatch, tmp_path):
    from openpilot.system.hardware import usb
    for name, vid, pid in (("1-1", "174c", "2464"), ("1-2", "0bda", "8153")):
      d = tmp_path / name
      d.mkdir()
      (d / "idVendor").write_text(vid)
      (d / "idProduct").write_text(pid)
    monkeypatch.setattr(usb, "USB_DEVICES_PATH", tmp_path)
    assert ja.Adapter().chestnut_present() is True
    (tmp_path / "1-1" / "idVendor").write_text("1d6b")
    assert ja.Adapter().chestnut_present() is False


class TestParams:
  def test_every_key_is_declared_with_the_type_jetlink_expects(self):
    k = ja.KEYS
    assert declared(k.link) == "INT"
    assert declared(k.offroad) == "BOOL"
    assert declared(k.progress) == "JSON"
    assert declared(k.spec) == "JSON"
    assert declared(k.pointers) == "JSON"
    assert declared(k.charge_phone) == "BOOL"
    assert declared("Offroad_JetlinkUnavailable") == "JSON"

  def test_the_chestnut_model_slot_is_not_handed_to_jetlink(self):
    # ActiveBigModel is a Chestnut model-key STRING; Jetlink has its own pick and catalog params (see test_picker.py)
    assert ja.KEYS.big_model == "JetlinkBigModel" and ja.KEYS.catalog == "JetlinkCatalog"
    assert "ActiveBigModel" not in ja.KEYS

  def test_native_gpu_params_are_not_reused(self):
    assert not any(str(v).startswith("UsbGpu") for v in ja.KEYS)

  def test_the_directory_follows_params_root_and_the_prefix(self, monkeypatch, tmp_path):
    monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENPILOT_PREFIX", raising=False)
    assert ja._params_dir() == tmp_path / "d"
    monkeypatch.setenv("OPENPILOT_PREFIX", "abc")
    assert ja._params_dir() == tmp_path / "abc"

  def test_the_directory_is_where_params_writes(self):
    p = Params()
    assert Path(p.get_param_path(ja.KEYS.link)) == ja._params_dir() / ja.KEYS.link

  def test_the_owner_reads_what_params_wrote(self):
    """Jetlink reads the link setting and IsOffroad as bare files; Params writes them. A change on either side fails here."""
    from jetlink.openpilot.settings import FileParams, Settings
    from jetlink.openpilot.interface import Keys
    p = Params()
    settings = Settings(FileParams(ja._params_dir()), Keys(**ja.KEYS._asdict()))
    old = (p.get(ja.KEYS.link), p.get(ja.KEYS.offroad))
    try:
      for index, mode in enumerate(ja.MODES):
        p.put(ja.KEYS.link, index)
        assert settings.mode() == mode
        assert ja.stored_mode() == mode
      p.put_bool(ja.KEYS.offroad, False)
      assert settings.offroad() is False
      p.put_bool(ja.KEYS.offroad, True)
      assert settings.offroad() is True
    finally:
      if old[0] is None:
        p.remove(ja.KEYS.link)
      else:
        p.put(ja.KEYS.link, old[0])
      if old[1] is None:
        p.remove(ja.KEYS.offroad)
      else:
        p.put_bool(ja.KEYS.offroad, bool(old[1]))

  def test_json_values_round_trip_through_the_adapter(self):
    op = ja.Adapter()
    value = {"stage": "connect", "frac": 0.5, "msg": "waiting", "drops": 0}
    try:
      op.put(ja.KEYS.progress, value, block=True)
      assert op.get(ja.KEYS.progress) == value
      op.remove(ja.KEYS.progress)
      assert op.get(ja.KEYS.progress) is None
    finally:
      op.remove(ja.KEYS.progress)

  def test_unknown_keys_read_as_unset_rather_than_raising(self):
    assert ja.Adapter().get("NoSuchJetlinkKey") is None

  def test_put_blocks_only_when_asked_to(self):
    calls = []
    fake = types.SimpleNamespace(put=lambda k, v: calls.append(("put", k, v)),
                                 put_nonblocking=lambda k, v: calls.append(("nb", k, v)))
    op = ja.Adapter()
    op._stores[ja._params_dir()] = fake
    op.put("K", 1)
    op.put("K", 2, block=True)
    assert calls == [("nb", "K", 1), ("put", "K", 2)]

  def test_downloads_sit_under_the_model_managers_root_where_it_cannot_prune_them(self):
    from openpilot.starpilot.assets import model_manager as mm
    root = ja.Adapter().model_root()
    assert root == Path(mm.MODELS_PATH)
    # ModelManager only ever removes top-level *files* named like driving artifacts
    assert not mm.is_driving_artifact_file("404a18cfd86d2963.onnx")
    assert (root / "jetlink").suffix == "" and not mm.is_driving_artifact_file("jetlink")


class TestTheDevice:
  def test_the_camera_is_one_modeld_has_a_warp_name_for(self):
    cam_w, cam_h, model_w, model_h = ja.Adapter().camera()
    assert (cam_w, cam_h) in ((1928, 1208), (1344, 760))
    assert (model_w, model_h) == (512, 256)

  def test_the_warp_path_is_in_the_forks_tree_and_per_geometry(self):
    path = ja.Adapter().warp_path(1928, 1208, 512, 256)
    assert path == ja.WARP_DIR / "warp_1928x1208_512x256_tinygrad.pkl"
    assert ja.WARP_DIR.is_relative_to(REPO)
    assert path != ja.Adapter().warp_path(1344, 760, 512, 256)

  def test_the_model_face_uses_the_forks_parser_and_frame_size(self):
    from openpilot.selfdrive.modeld.constants import ModelConstants
    from openpilot.selfdrive.modeld.parse_model_outputs import Parser
    face = ja.Adapter().model_face()
    assert face.parser is Parser
    assert face.desire_len == ModelConstants.DESIRE_LEN == 8
    assert face.frame_size(1928, 1208) == 3190784 or face.frame_size(1928, 1208) > 0

  def test_make_warp_passes_the_forks_explicit_history_arguments(self, monkeypatch):
    """compile_modeld.make_warp needs frame_skip; the policy-history graph is the one with the four-name call."""
    import openpilot.selfdrive.modeld.compile_modeld as cm
    seen = {}

    def fake(nv12, model_w, model_h, frame_skip, image_history_pipeline=None, device=None):
      seen.update(frame_skip=frame_skip, pipeline=image_history_pipeline, nv12=nv12)
      return "graph"
    monkeypatch.setattr(cm, "make_warp", fake)
    graph, size = ja.Adapter().make_warp(1928, 1208, 512, 256)
    assert graph == "graph" and size == seen["nv12"].size > 0
    assert seen["pipeline"] == cm.IMAGE_HISTORY_IN_POLICY and seen["frame_skip"] == 1


class TestModes:
  def test_every_jetlink_mode_is_offered(self):
    assert ja.SUPPORTED_MODES == ("off", "usb", "ios")

  def _set_mode(self, monkeypatch, tmp_path, index):
    (tmp_path / "d").mkdir(exist_ok=True)
    (tmp_path / "d" / ja.KEYS.link).write_text(str(index))
    monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENPILOT_PREFIX", raising=False)

  def test_ios_is_a_supported_mode(self, monkeypatch, tmp_path):
    self._set_mode(monkeypatch, tmp_path, 2)
    assert ja.stored_mode() == "ios"
    assert ja._wanted() is True

  def test_off_never_imports_jetlink_or_nags(self, monkeypatch, tmp_path):
    self._set_mode(monkeypatch, tmp_path, 0)
    monkeypatch.setattr(ja, "_bind", lambda: pytest.fail("imported Jetlink for a device with the link off"))
    assert ja.should_run(True, None, None) is False
    assert ja.prepare() is False
    assert ja.reason() is None

  def test_an_unreadable_or_out_of_range_setting_is_off(self, monkeypatch, tmp_path):
    self._set_mode(monkeypatch, tmp_path, 9)
    assert ja.stored_mode() == "off"
    monkeypatch.setenv("PARAMS_ROOT", str(tmp_path / "nowhere"))
    assert ja.stored_mode() == "off"


class TestWithoutAUsableJetlink:
  """Absent, from another API, or failing: every hook answers as if the link were off, and says why to someone who turned it on."""

  def _link_on(self, monkeypatch, tmp_path):
    (tmp_path / "d").mkdir(exist_ok=True)
    (tmp_path / "d" / ja.KEYS.link).write_text("1")
    monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENPILOT_PREFIX", raising=False)

  def _hide_jetlink(self, monkeypatch, tmp_path):
    for name in [m for m in sys.modules if m == "jetlink" or m.startswith("jetlink.")]:
      monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(ja, "VENDOR_DIR", tmp_path / "no-vendor")
    monkeypatch.setattr(sys, "path", [p for p in sys.path if "jetlink_repo" not in p])

  def test_without_the_package_every_hook_is_the_link_off(self, monkeypatch, tmp_path):
    self._link_on(monkeypatch, tmp_path)
    self._hide_jetlink(monkeypatch, tmp_path)
    assert ja.should_run(True, None, None) is False
    assert ja.status() is None
    assert ja.reason() is None   # not vendored at all: the feature does not exist here, nothing to nag about
    assert ja.prepare() is False
    assert ja.attach(object(), 1928, 1208) is None
    assert ja.request_shutdown("x") is False
    assert ja.shutdown_pending() is False
    assert ja.model_state("ref") is None

  def test_another_api_turns_the_link_off_and_says_why(self, monkeypatch, tmp_path):
    self._link_on(monkeypatch, tmp_path)
    import jetlink.openpilot as jl
    monkeypatch.setattr(jl, "API", 3)
    assert ja.should_run(True, None, None) is False
    assert "API 3" in ja.reason() and "expects 2" in ja.reason()
    assert ja.prepare() is False and ja.attach(object(), 1, 1) is None

  def test_a_package_that_fails_to_import_says_so(self, monkeypatch, tmp_path):
    self._link_on(monkeypatch, tmp_path)
    monkeypatch.setattr(ja, "_bind", lambda: ja._unusable("jetlink failed to load: ImportError: boom"))
    assert ja.should_run(True, None, None) is False
    assert "boom" in ja.reason()

  def test_a_failing_jetlink_never_raises_into_its_caller(self, monkeypatch, tmp_path):
    self._link_on(monkeypatch, tmp_path)

    class Broken:
      def __getattr__(self, name):
        def fail(*a, **k):
          raise RuntimeError(f"{name} blew up")
        return fail
    monkeypatch.setattr(ja, "_bound", Broken())
    assert ja.should_run(True, None, None) is False
    assert ja.status() is None
    assert ja.reason() is None
    assert ja.prepare() is False
    assert ja.attach(object(), 1, 1) is None
    assert ja.request_shutdown() is False
    assert ja.shutdown_pending() is False
    assert ja.in_control(types.SimpleNamespace(all_alive=lambda s: (_ for _ in ()).throw(RuntimeError()))) is True

  def test_a_failure_is_logged_again_once_it_changes_or_has_cleared(self, monkeypatch, tmp_path):
    self._link_on(monkeypatch, tmp_path)
    logged = []
    monkeypatch.setattr(ja, "_log_failure", lambda what, error: logged.append(what))
    state = {"fail": True}

    class Flaky:
      def enabled(self):
        if state["fail"]:
          raise RuntimeError("x")
        return True
    monkeypatch.setattr(ja, "_bound", Flaky())
    for _ in range(5):
      ja.should_run(True, None, None)
    assert len(logged) == 1
    state["fail"] = False
    assert ja.should_run(True, None, None) is True
    state["fail"] = True
    ja.should_run(True, None, None)
    assert len(logged) == 2


class FakeSm:
  def __init__(self, enabled=False, lat=False, long=False, aol_enabled=False, aol_allowed=False, alive=True, valid=True):
    self._alive, self._valid = alive, valid
    self._d = {"carControl": types.SimpleNamespace(enabled=enabled, latActive=lat, longActive=long),
               "starpilotCarState": types.SimpleNamespace(alwaysOnLateralEnabled=aol_enabled, alwaysOnLateralAllowed=aol_allowed),
               "carState": types.SimpleNamespace()}

  def all_alive(self, services):
    return self._alive

  def all_valid(self, services):
    return self._valid

  def __getitem__(self, k):
    return self._d[k]


class TestInControl:
  """The swap gate: False (free to swap) only when nothing is, or is about to be, in control."""

  def test_idle_car_is_free(self):
    assert ja.in_control(FakeSm()) is False

  @pytest.mark.parametrize("kwargs", [{"enabled": True}, {"lat": True}, {"long": True}, {"aol_enabled": True}])
  def test_engagement_blocks_the_swap(self, kwargs):
    assert ja.in_control(FakeSm(**kwargs)) is True

  def test_a_paused_always_on_lateral_that_will_resume_blocks_the_swap(self):
    # latActive False, AOL not 'enabled' this tick (blinker / brake), but armed: it steers again by itself
    sm = FakeSm(aol_allowed=True)
    assert ja.in_control(sm) is True

  def test_armed_flag_is_ignored_on_a_car_that_cannot_run_aol(self):
    assert ja.in_control(FakeSm(aol_allowed=True), aol_possible=False) is False

  def test_stale_or_invalid_inputs_count_as_in_control(self):
    assert ja.in_control(FakeSm(alive=False)) is True
    assert ja.in_control(FakeSm(valid=False)) is True
