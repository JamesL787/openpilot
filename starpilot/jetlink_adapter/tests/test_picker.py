"""The big-model picker: Jetlink's catalog, the validated gate under it, and the Galaxy endpoint over both.

Ported in spirit from peterfork/Jetlink-Port (catalog, pick, Galaxy cards); what differs is the gate: a model can be picked only
if starpilot/jetlink_adapter/profiles.py has validated it, so a pick can never be one the join would then refuse."""
import types
from pathlib import Path

import pytest

from openpilot.common.params import Params
from openpilot.starpilot import jetlink_adapter as ja
from openpilot.starpilot.jetlink_adapter import profiles

GOOD = profiles.CINQUE_TERRE_V3.ref
OTHER = "a" * 40
FUTURE = "b" * 40
VALIDATED = {p.ref: p for p in profiles.PROFILES.values()}
REPO = Path(__file__).resolve().parents[3]


def bundle(ref, name, index, selector=None):
  from jetlink.registry.catalog import REQUIRED_SELECTOR_VERSION
  return {"ref": ref, "display_name": name, "index": index,
          "minimum_selector_version": REQUIRED_SELECTOR_VERSION if selector is None else selector}


@pytest.fixture
def store(monkeypatch, tmp_path):
  """A real Params store under a temporary root, with the link on (USB)."""
  monkeypatch.setenv("PARAMS_ROOT", str(tmp_path))
  monkeypatch.setenv("OPENPILOT_PREFIX", "picker-test")
  monkeypatch.setattr(ja, "_store", None)
  p = Params()
  p.put(ja.KEYS.link, 1)
  return p


def put_catalog(p, *bundles):
  p.put(ja.KEYS.catalog, {"bundles": list(bundles)})


class TestKeys:
  def test_the_picks_are_jetlinks_own_and_not_the_model_managers(self):
    assert (ja.KEYS.big_model, ja.KEYS.catalog) == ("JetlinkBigModel", "JetlinkCatalog")
    assert ja.KEYS.big_model != "ActiveBigModel"     # a Chestnut model-key STRING, never handed to Jetlink
    assert ja.Adapter().catalog_selector > 0

  def test_both_are_json_params(self):
    from openpilot.starpilot.jetlink_adapter.tests.test_adapter import declared
    assert declared("JetlinkBigModel") == "JSON" and declared("JetlinkCatalog") == "JSON"


class TestTheRows:
  def test_the_catalog_is_listed_newest_first_with_what_is_validated(self, store):
    put_catalog(store, bundle(OTHER, "Older", 1), bundle(GOOD, "Cinque Terre V3 Model", 5), bundle(FUTURE, "Newest", 9),
                bundle("c" * 40, "Wrong selector", 99, selector=999), bundle(GOOD, "Duplicate", 2), {"ref": "short"})
    rows = ja.models()
    # the validated models the catalog did not list are added at index 0, after everything it did
    added = [f"{p.name} Model" for ref, p in VALIDATED.items() if ref != GOOD]
    assert [r["name"] for r in rows] == ["Newest", "Cinque Terre V3 Model", "Older", *added]
    assert {r["ref"]: r["supported"] for r in rows} == {FUTURE: False, OTHER: False, **dict.fromkeys(VALIDATED, True)}
    assert not any(r["selected"] for r in rows)

  def test_the_pick_is_marked(self, store):
    put_catalog(store, bundle(GOOD, "Cinque Terre V3 Model", 5))
    store.put(ja.KEYS.big_model, {"ref": GOOD, "displayName": "x"})
    assert {r["ref"] for r in ja.models() if r["selected"]} == {GOOD}

  def test_a_missing_catalog_still_offers_the_validated_models_so_an_offline_comma_can_join(self, store):
    rows = ja.models()
    assert {(r["ref"], r["supported"]) for r in rows} == {(ref, True) for ref in VALIDATED}

  def test_a_fetched_catalog_that_no_longer_lists_the_pinned_model_does_not_lose_it(self, store):
    put_catalog(store, bundle(FUTURE, "Newest", 9))
    assert {r["ref"] for r in ja.models()} == {FUTURE, *VALIDATED}

  def test_jetlinks_default_is_the_pinned_validated_model_whatever_else_the_catalog_lists(self, store):
    from jetlink.openpilot.models import Models
    from jetlink.registry.catalog import DEFAULT_BIG_MODEL_REF
    assert DEFAULT_BIG_MODEL_REF == GOOD
    for catalog in (None, {"bundles": [bundle(FUTURE, "Newest", 9)]}):
      if catalog is not None:
        store.put(ja.KEYS.catalog, catalog)
      models = Models(ja.Adapter())
      assert models.default_model()["ref"] == GOOD and models.selected_model()["ref"] == GOOD

  def test_a_mode_this_build_refuses_lists_nothing(self, store):
    put_catalog(store, bundle(GOOD, "x", 1))
    store.put(ja.KEYS.link, 2)
    assert ja.models() == []


class TestPicking:
  def test_a_validated_model_can_be_picked_and_the_default_restored(self, store):
    put_catalog(store, bundle(GOOD, "Cinque Terre V3 Model", 5))
    assert ja.select_model(GOOD) == (True, "")
    assert store.get(ja.KEYS.big_model) == {"ref": GOOD, "displayName": "Cinque Terre V3 Model"}
    assert ja.select_model("") == (True, "") and store.get(ja.KEYS.big_model) is None
    assert ja.select_model(None) == (True, "")

  def test_an_unvalidated_model_is_refused_with_the_reason_and_nothing_is_written(self, store):
    put_catalog(store, bundle(GOOD, "Cinque Terre V3 Model", 5), bundle(FUTURE, "Newest", 9))
    ok, message = ja.select_model(FUTURE)
    assert not ok and "not been validated" in message and "Newest" in message
    assert store.get(ja.KEYS.big_model) is None

  def test_an_unknown_ref_is_refused(self, store):
    put_catalog(store, bundle(GOOD, "x", 1))
    ok, message = ja.select_model(OTHER)
    assert not ok and "Unknown" in message

  def test_a_stored_pick_that_is_no_longer_validated_is_reported_to_the_driver(self, store, monkeypatch):
    store.put(ja.KEYS.big_model, {"ref": FUTURE, "displayName": "Newest"})
    monkeypatch.setattr(ja, "_bound", types.SimpleNamespace(reason=lambda: None))
    assert "has not been validated" in ja.reason() and "default" in ja.reason()
    store.put(ja.KEYS.big_model, {"ref": GOOD, "displayName": "ok"})
    assert ja.reason() is None


class TestRefresh:
  def test_it_fetches_only_for_someone_who_turned_the_link_on(self, store, monkeypatch):
    monkeypatch.setattr(ja, "_bound", types.SimpleNamespace(
      should_extend_catalog=lambda: True, extend_catalog=lambda c: pytest.fail("fetched with the link off")))
    store.put(ja.KEYS.link, 0)
    assert ja.refresh_catalog() is False

  def test_a_new_catalog_is_stored_and_an_unchanged_or_failed_one_is_not(self, store, monkeypatch):
    merged = {"bundles": [bundle(GOOD, "Cinque Terre V3 Model", 5)]}
    api = types.SimpleNamespace(should_extend_catalog=lambda: True, extend_catalog=lambda c: merged)
    monkeypatch.setattr(ja, "_bound", api)
    assert ja.refresh_catalog() is True and store.get(ja.KEYS.catalog) == merged   # stored as fetched (the pinned model is already in it)
    assert ja.refresh_catalog() is False                                  # unchanged
    api.extend_catalog = lambda c: {"bundles": []}
    assert ja.refresh_catalog() is False and store.get(ja.KEYS.catalog) == merged   # a failed probe keeps the last

  def test_a_chestnut_is_never_given_a_catalog(self, store, monkeypatch):
    monkeypatch.setattr(ja, "_bound", types.SimpleNamespace(should_extend_catalog=lambda: False))
    assert ja.refresh_catalog() is False

  def test_a_failing_fetch_never_raises_into_the_model_manager(self, store, monkeypatch):
    def boom(c):
      raise RuntimeError("network")
    monkeypatch.setattr(ja, "_bound", types.SimpleNamespace(should_extend_catalog=lambda: True, extend_catalog=boom))
    assert ja.refresh_catalog() is False

  def test_the_model_manager_refreshes_it_with_its_own_update(self):
    src = (REPO / "starpilot/assets/model_manager.py").read_text()
    update = src[src.index("  def update_models"):src.index("  def download_model")]
    assert "jetlink_adapter.refresh_catalog()" in update


class FakeParams:
  def __init__(self, onroad=False):
    self.onroad = onroad

  def get_bool(self, key, **kw):
    return self.onroad if key == "IsOnroad" else False

  def get(self, key, **kw):
    return kw.get("default")


@pytest.fixture
def client(monkeypatch, request):
  from openpilot.starpilot.system.the_galaxy import the_galaxy
  fake = FakeParams()
  monkeypatch.setattr(the_galaxy, "params", fake)
  assert the_galaxy._import_galaxy_web_symbols()
  app = the_galaxy.Flask("jetlink_picker_test")
  the_galaxy.setup(app)
  c = app.test_client()
  c.fake = fake
  return c


class TestGalaxyEndpoint:
  def status(self, **kw):
    base = dict(mode="usb", enabled=True, present=True, transport="USB", ready=True, reason=None, progress=None, model="X",
                default_model="Cinque Terre V3", active_model="Cinque Terre V3")
    base.update(kw)
    return types.SimpleNamespace(**base)

  def test_get_lists_models_with_their_validation(self, client, monkeypatch):
    monkeypatch.setattr(ja, "status", lambda: self.status())
    monkeypatch.setattr(ja, "reason", lambda: None)
    monkeypatch.setattr(ja, "models", lambda: [{"ref": GOOD, "name": "Cinque Terre V3 Model", "state": "ready", "selected": True,
                                                "supported": True}, {"ref": FUTURE, "name": "Newest", "state": None, "selected": False,
                                                                     "supported": False}])
    r = client.get("/api/models/jetlink")
    body = r.get_json()
    assert r.status_code == 200 and body["available"] and body["mode"] == "usb" and body["defaultModel"] == "Cinque Terre V3"
    assert [m["supported"] for m in body["models"]] == [True, False]

  def test_it_says_unavailable_without_jetlink(self, client, monkeypatch):
    monkeypatch.setattr(ja, "status", lambda: None)
    monkeypatch.setattr(ja, "models", list)
    assert client.get("/api/models/jetlink").get_json()["available"] is False

  def test_a_pick_while_driving_is_refused(self, client, monkeypatch):
    client.fake.onroad = True
    monkeypatch.setattr(ja, "select_model", lambda ref: pytest.fail("changed the model while driving"))
    r = client.put("/api/models/jetlink", json={"ref": GOOD})
    assert r.status_code == 403

  @pytest.mark.parametrize("message,code", [("Unknown Jetlink model aaaaaaaaaa", 404),
                                            ("Newest has not been validated on this fork; only validated models can be picked", 409)])
  def test_a_refused_pick_says_why(self, client, monkeypatch, message, code):
    monkeypatch.setattr(ja, "select_model", lambda ref: (False, message))
    r = client.put("/api/models/jetlink", json={"ref": OTHER})
    assert r.status_code == code and r.get_json()["error"] == message

  def test_a_bad_request_is_a_400_and_a_good_pick_returns_the_listing(self, client, monkeypatch):
    assert client.put("/api/models/jetlink", json={"ref": 5}).status_code == 400
    picked = []
    monkeypatch.setattr(ja, "select_model", lambda ref: picked.append(ref) or (True, ""))
    monkeypatch.setattr(ja, "status", lambda: self.status())
    monkeypatch.setattr(ja, "reason", lambda: None)
    monkeypatch.setattr(ja, "models", list)
    assert client.put("/api/models/jetlink", json={"ref": GOOD}).status_code == 200
    assert client.put("/api/models/jetlink", json={"ref": ""}).status_code == 200
    assert picked == [GOOD, None]

  def test_the_frontend_modules_are_wired_and_gate_unvalidated_models(self):
    a = REPO / "starpilot/system/the_galaxy/assets"
    desktop = (a / "components/tools/jetlink_models.js").read_text()
    mobile = (a / "mobile/js/components/JetlinkModelsCard.js").read_text()
    assert "Not validated" in desktop and "supported === false" in desktop
    assert "Not validated" in mobile and "supported === false" in mobile
    assert "JetlinkModels()" in (a / "components/tools/model_manager.js").read_text()
    assert "JetlinkModelsCard" in (a / "mobile/js/views/ModelManager.js").read_text()
