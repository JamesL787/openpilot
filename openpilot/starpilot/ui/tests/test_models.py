"""Model identity remains separate from guarded catalog management."""

import unittest
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest import mock

from openpilot.starpilot.models.catalog import BUNDLED_CURRENT, BY_ID
from openpilot.starpilot.models.status import ModelHealth, ModelStatus, ModelVariant
from openpilot.starpilot.ui.feature_settings_state import feature_row_top, FeatureInput
from openpilot.starpilot.ui.models_compact import ModelsCompact, _ModelsPage, _display_text
from openpilot.starpilot.ui.models_state import (model_page, model_action_allowed, model_catalog_rows, model_profile_choices, model_profile_request,
                                                home_model_label, model_download_choices)
from openpilot.starpilot.ui.presentation import Profile
from openpilot.starpilot.ui.settings_state import Destination
from openpilot.starpilot.ui.shell import ShellMode, ShellView


class TestModelPage(unittest.TestCase):
  def test_runtime_stall_has_truthful_fallback_wording(self):
    status = ModelStatus(BUNDLED_CURRENT, BUNDLED_CURRENT, ModelVariant.SMALL, ModelHealth.ACTIVE,
                         False, 'chestnut-run-stalled', 'a' * 64)
    rows = model_page(status).rows
    fallback = next(row for row in rows if row.label == 'Fallback')
    self.assertEqual(fallback.reason, 'Chestnut output stopped; Small restarted for this drive')
    self.assertNotIn('load', fallback.reason.lower())

  def test_native_display_normalizes_unsupported_glyphs_only(self):
    label = "Green Watermelon v8 👀📡"
    self.assertEqual(_display_text(label), "Green Watermelon v8")
    self.assertEqual(label, "Green Watermelon v8 👀📡")
    self.assertEqual(_display_text("2 installed · 98 missing"), "2 installed • 98 missing")
    self.assertEqual(_display_text("none — always use small"), "none – always use small")
    self.assertEqual(_display_text("TR17 ⚡️  v8"), "TR17 v8")
    self.assertEqual(_display_text("gwm8223"), "gwm8223")

  def test_home_prefers_verified_loaded_identity_over_pending_selection(self):
    requested = next(model_id for model_id in BY_ID if model_id != BUNDLED_CURRENT)
    status = ModelStatus(requested, BUNDLED_CURRENT, ModelVariant.SMALL, ModelHealth.ACTIVE, True, None, "a" * 64)
    actual = "CD210"
    commit = "abcdef1234567890" * 2 + "abcdef12"
    for health in (ModelHealth.ACTIVE, ModelHealth.STALE, ModelHealth.LOADING):
      self.assertEqual(home_model_label(replace(status, health=health), commit), f"{actual} • abcdef1")
    self.assertEqual(home_model_label(replace(status, loaded_id=None, health=ModelHealth.UNAVAILABLE), commit),
                     f"{_display_text(BY_ID[requested].name)} • abcdef1")
    self.assertEqual(home_model_label(status), actual)
    self.assertEqual(home_model_label(replace(status, variant=ModelVariant.CHESTNUT)), "Cinque v2")
    self.assertEqual(home_model_label(status, "not-a-revision"), actual)

  def test_bundled_identity_health_and_inert_rows(self):
    status = ModelStatus(BUNDLED_CURRENT, BUNDLED_CURRENT, ModelVariant.SMALL, ModelHealth.ACTIVE,
                         False, None, "a" * 64)
    page = model_page(status)
    self.assertEqual(page.title, "Driving Model")
    self.assertEqual(page.rows[1].value, "Active")
    self.assertEqual(page.rows[2].value, "Small")
    self.assertTrue(all(not row.available and not row.page for row in page.rows))
    self.assertIsNone(FeatureInput.target(1980, 300, page))
    self.assertIsNone(FeatureInput.target(600, 60, page))
    self.assertEqual(FeatureInput.target(100, 60, replace(page, sidebar_expanded=False)).kind, "back")

  def test_missing_receipt_does_not_look_active(self):
    status = ModelStatus(BUNDLED_CURRENT, None, None, ModelHealth.IDENTITY_UNAVAILABLE,
                         False, None, None)
    page = model_page(status)
    self.assertEqual(page.rows[1].value, "Identity unavailable")
    self.assertEqual(page.rows[3].value, "Unavailable")
    self.assertIn("No verified load receipt", page.rows[3].reason)

  def test_large_shell_renders_model_pane_without_controls(self):
    status = ModelStatus(BUNDLED_CURRENT, None, None, ModelHealth.UNAVAILABLE, False, None, None)
    page = model_page(status)
    view = ShellView.__new__(ShellView)
    view.profile = Profile.LARGE
    view.models = mock.Mock()
    view.settings = mock.Mock()
    view.onroad = mock.Mock()
    shell = mock.Mock(mode=ShellMode.SETTINGS, selected=Destination.DRIVING_MODEL, models=page, settings=mock.Mock())
    view.render(shell)
    view.models.render.assert_called_once_with(page, 0.0)
    view.settings.render_rail.assert_called_once_with(shell.settings, selected=Destination.STAR)

  def test_compact_visible_page_refreshes_and_hidden_page_does_not_sample(self):
    active = model_page(ModelStatus(BUNDLED_CURRENT, BUNDLED_CURRENT, ModelVariant.SMALL,
                                    ModelHealth.ACTIVE, False, None, "a" * 64))
    stale = model_page(ModelStatus(BUNDLED_CURRENT, BUNDLED_CURRENT, ModelVariant.SMALL,
                                   ModelHealth.STALE, False, None, "a" * 64))
    absent = model_page(ModelStatus(BUNDLED_CURRENT, None, None,
                                    ModelHealth.UNAVAILABLE, False, None, None))
    session = mock.Mock()
    session.model_snapshot.side_effect = [stale, absent]
    now = [0.0]
    owner = ModelsCompact(session, clock=lambda: now[0])
    scroller = mock.Mock(items=[])
    page = cast(_ModelsPage, SimpleNamespace(current=active, next_refresh=0.5, _scroller=scroller))
    with mock.patch("openpilot.starpilot.ui.models_compact.GreyBigButton", side_effect=lambda *args: args), \
         mock.patch("openpilot.starpilot.ui.models_compact.gui_app.get_active_widget", return_value=page) as visible:
      now[0] = 0.49
      owner.refresh_visible(page)
      session.model_snapshot.assert_not_called()
      now[0] = 0.5
      owner.refresh_visible(page)
      self.assertEqual(page.current, stale)
      self.assertIn("model output stale", scroller.add_widgets.call_args.args[0][2][1])
      visible.return_value = object()
      now[0] = 2.0
      owner.refresh_visible(page)
      self.assertEqual(session.model_snapshot.call_count, 1)
      visible.return_value = page
      owner.refresh_visible(page)
      self.assertEqual(page.current, absent)
      self.assertIn("model not running", scroller.add_widgets.call_args.args[0][2][1])
      self.assertEqual(session.model_snapshot.call_count, 2)


class TestModelManager(unittest.TestCase):
  def setUp(self):
    self.small = {"value": "small", "label": "Small", "installed": True, "selectable": True, "requiresGpu": False}
    self.big = {"value": "big", "label": "Big", "installed": True, "selectable": True, "requiresGpu": True, "userFavorite": True}
    self.pending = {"value": "pending", "label": "Pending", "installed": False, "selectable": False, "requiresGpu": False,
                    "communityFavorite": True, "downloadAvailable": False}
    self.missing = {"value": "missing", "label": "Missing", "installed": False, "selectable": False, "requiresGpu": True,
                    "downloadAvailable": True, "gpuAvailable": False}
    self.data: dict[str, Any] = {"schemaVersion": 1, "models": [self.small, self.big, self.pending, self.missing], "isOnroad": False,
                 "activeSmallModel": "small", "activeBigModel": "big", "currentModel": "small", "downloading": False,
                 "capabilities": {"select": True, "download": True, "downloadAll": True, "favorites": True, "delete": True, "cancel": True,
                                  "randomizer": True, "exclusions": True}}

  def test_verified_profiles_and_pending_catalog_are_distinct(self):
    self.assertEqual(model_profile_choices(self.data, "small"), (("Small", "small"),))
    self.assertEqual(model_profile_choices(self.data, "big"), (("None – always use Active Small", ""), ("Big", "big")))
    self.assertEqual(model_profile_choices(self.data | {"models": [self.small | {"label": "Small 👀📡"}]}, "small"), (("Small", "small"),))
    self.assertEqual(model_profile_request(self.data, "big", ""), {"profile": "big", "model": ""})
    self.assertIsNone(model_profile_request(self.data, "big", "small"))
    self.assertIsNone(model_profile_request(self.data, "small", "pending"))
    self.assertFalse(model_action_allowed(self.data, "download", self.pending))
    self.assertTrue(model_action_allowed(self.data, "download", self.missing))
    self.assertEqual([m["value"] for m in model_catalog_rows(self.data, "community")], ["pending"])
    self.assertEqual([m["value"] for m in model_catalog_rows(self.data, "favorites")], ["big"])

  def test_parked_and_protected_guards(self):
    self.assertFalse(model_action_allowed(self.data, "delete", self.big))
    self.assertTrue(model_action_allowed({**self.data, "activeBigModel": ""}, "delete", self.big))
    self.assertFalse(model_action_allowed({**self.data, "capabilities": {}}, "active", self.small, "small"))
    moving = {**self.data, "isOnroad": True, "downloading": True}
    self.assertFalse(model_action_allowed(moving, "active", self.small, "small"))
    self.assertTrue(model_action_allowed(moving, "preferences", self.small))
    self.assertTrue(model_action_allowed(moving, "cancel"))

  def test_large_profile_rows_are_open_actions_and_receipt_stays_inert(self):
    state = model_page(ModelStatus(BUNDLED_CURRENT, None, None, ModelHealth.UNAVAILABLE, False, None, None), self.data)
    self.assertEqual(state.rows[1].value, "Small")
    self.assertEqual(state.rows[1].source, b"small")
    action = FeatureInput.target(1000, feature_row_top(state) + 288, state)
    self.assertEqual((action.kind, action.row.page), ("open", "models:small"))
    self.assertTrue(all(not row.available for row in state.rows[3:]))

  def test_catalog_count_is_honest_and_download_rows_follow_the_owner(self):
    status = ModelStatus(BUNDLED_CURRENT, None, None, ModelHealth.UNAVAILABLE, False, None, None)
    data: dict[str, Any] = self.data | {"summary": {"installed": 2, "total": 4}}
    state = model_page(status, data)
    self.assertEqual(state.rows[0].value, "2 installed / 4 in catalog")
    self.assertEqual([row.label for row in state.rows[3:6]], ["Download a model", "Download all missing", "Refresh catalog"])
    # The only missing model needs a GPU this device lacks, and the fixture has no refresh capability.
    self.assertEqual(model_download_choices(data), ())
    self.assertFalse(any(row.available for row in state.rows[3:6]))
    fetchable = {"value": "fetch", "label": "Fetch", "installed": False, "requiresGpu": False, "downloadAvailable": True}
    data = data | {"models": data["models"] + [fetchable], "capabilities": data["capabilities"] | {"refresh": True}}
    self.assertEqual(model_download_choices(data), (("Fetch (Small)", "fetch"),))
    self.assertEqual(model_download_choices(data | {"models": data["models"] + [fetchable | {"value": "f2", "checking": True}]}),
                     (("Fetch (Small)", "fetch"),))
    self.assertEqual(model_download_choices(data | {"models": data["models"] + [fetchable | {"value": "f2"}]}),
                     (("Fetch (Small) [fetch]", "fetch"), ("Fetch (Small) [f2]", "f2")))
    self.assertEqual(model_page(status, data | {"progress": "Downloaded!"}).rows[0].reason, "Last job: Downloaded!")
    self.assertEqual(model_download_choices(data | {"models": data["models"] + [self.missing | {"gpuAvailable": True}]}),
                     (("Fetch (Small)", "fetch"), ("Missing (Big)", "missing")))
    rows = model_page(status, data).rows
    self.assertEqual([(row.page, row.available) for row in rows[3:6]],
                     [("models:download", True), ("models:download_all", True), ("models:refresh_manifest", True)])
    rows = model_page(status, data | {"isOnroad": True}).rows
    self.assertFalse(any(row.available for row in rows[3:6]))
    rows = model_page(status, data | {"downloading": True, "progress": "40%"}).rows
    self.assertEqual([(row.label, row.value, row.available) for row in rows[3:6]],
                     [("Download a model", "None to download", False), ("Cancel download", "40%", True), ("Refresh catalog", "Check for new models", False)])
    self.assertEqual({row.reason for row in rows[1:3]}, {"Wait for the download to finish"})
    rows = model_page(status, data | {"isOnroad": True, "downloading": True}).rows
    self.assertEqual({row.reason for row in rows[1:3]}, {"Turn the vehicle off to change models"})

  def _session(self, data):
    from openpilot.starpilot.ui import runtime_app
    session = runtime_app.StarShellSession.__new__(runtime_app.StarShellSession)
    session._mode, session.selected = ShellMode.SETTINGS, Destination.DRIVING_MODEL
    session._snapshot_cache = None
    session.notice, session.notice_until = "", 0.0
    session.model_manager_snapshot = mock.Mock(return_value=data)
    session.model_manager_action = mock.Mock(return_value={})
    session.model_snapshot = mock.Mock(side_effect=lambda: model_page(
      ModelStatus(BUNDLED_CURRENT, None, None, ModelHealth.UNAVAILABLE, False, None, None), session.model_manager_snapshot()))
    return session

  def _open(self, session, page):
    from openpilot.starpilot.ui.feature_settings_state import FeatureUiAction
    row = next(row for row in session.model_snapshot().rows if row.page == page)
    session._models_ui(FeatureUiAction("open", row))

  def test_large_selector_with_no_installed_small_model_explains_instead_of_opening_empty(self):
    session = self._session(self.data | {"models": [self.big, self.pending, self.missing]})
    with mock.patch("openpilot.system.ui.lib.application.gui_app.push_widget") as push:
      self._open(session, "models:small")
    push.assert_not_called()
    self.assertEqual(session.notice, "Unavailable: no installed Small model yet; use Download a model")
    session = self._session(self.data | {"models": [self.big, self.small | {"installed": False, "selectable": False, "checking": True}]})
    with mock.patch("openpilot.system.ui.lib.application.gui_app.push_widget") as push:
      self._open(session, "models:small")
    push.assert_not_called()
    self.assertEqual(session.notice, "Unavailable: still checking installed models; try again")

  def test_large_download_dialog_and_actions_recheck_a_fresh_snapshot(self):
    from openpilot.system.ui.widgets import DialogResult
    fetchable = {"value": "fetch", "label": "Fetch", "installed": False, "requiresGpu": False, "downloadAvailable": True}
    data = self.data | {"models": self.data["models"] + [fetchable], "capabilities": self.data["capabilities"] | {"refresh": True}}
    session = self._session(data)
    with mock.patch("openpilot.system.ui.lib.application.gui_app.push_widget") as push, \
         mock.patch("openpilot.system.ui.widgets.option_dialog.MultiOptionDialog") as dialog:
      self._open(session, "models:download")
      push.assert_called_once()
      self.assertEqual(dialog.call_args.args[1], ["Fetch (Small)"])
      callback = dialog.call_args.kwargs["callback"]
      dialog.return_value.selection = "Fetch (Small)"
      session.model_manager_snapshot.return_value = data | {"isOnroad": True}
      callback(DialogResult.CONFIRM)
      session.model_manager_action.assert_not_called()
      session.model_manager_snapshot.return_value = data
      callback(DialogResult.CANCEL)
      session.model_manager_action.assert_not_called()
      callback(DialogResult.CONFIRM)
      session.model_manager_action.assert_called_once_with("download", {"model": "fetch"})
    for page, kind in (("models:download_all", "download_all"), ("models:refresh_manifest", "refresh_manifest")):
      session.model_manager_action.reset_mock()
      self._open(session, page)
      session.model_manager_action.assert_called_once_with(kind, {})
    session.model_manager_snapshot.return_value = data | {"downloading": True}
    session.model_manager_action.reset_mock()
    self._open(session, "models:cancel")
    session.model_manager_action.assert_called_once_with("cancel", {})
    session.model_manager_action.side_effect = ValueError("manifest unreachable")
    session.model_manager_snapshot.return_value = data
    self._open(session, "models:refresh_manifest")
    self.assertEqual(session.notice, "Unavailable: manifest unreachable")

  def test_compact_catalog_keeps_installation_and_exclusion_visible_first(self):
    session = mock.Mock()
    data = self.data | {"models": [self.small | {"blacklisted": True, "userFavorite": True}]}
    owner = ModelsCompact(session)
    page = cast(_ModelsPage, SimpleNamespace(profile="", sort_mode="name"))
    with mock.patch("openpilot.starpilot.ui.models_compact.GreyBigButton"), \
         mock.patch("openpilot.starpilot.ui.models_compact.BigButton") as button:
      owner._catalog(page, data)
    self.assertEqual(button.call_args.args[1], "installed • excluded from randomizer • small • your favorite")

  def test_compact_writes_profile_and_favorites_to_owner(self):
    session = mock.Mock()
    session.model_manager_snapshot.return_value = self.data
    session.model_manager_action.return_value = {"message": "Saved for next start"}
    owner = ModelsCompact(session)
    page = cast(_ModelsPage, SimpleNamespace())
    with mock.patch("openpilot.starpilot.ui.models_compact.gui_app.get_active_widget", return_value=page), \
         mock.patch("openpilot.starpilot.ui.models_compact.gui_app.push_widget"), \
         mock.patch("openpilot.starpilot.ui.models_compact.BigDialog"), mock.patch.object(owner, "_populate"):
      owner._action(page, "active", "", "big")
      session.model_manager_action.assert_called_with("active", {"profile": "big", "model": ""})
      owner._action(page, "preferences", "small")
      session.model_manager_action.assert_called_with("preferences", {"userFavorites": ["big", "small"]})

  def test_gpu_confirmation_rechecks_parked_state(self):
    session = mock.Mock()
    session.model_manager_snapshot.return_value = self.data
    owner = ModelsCompact(session)
    page = cast(_ModelsPage, SimpleNamespace())
    with mock.patch("openpilot.starpilot.ui.models_compact.gui_app.get_active_widget", return_value=page), \
         mock.patch("openpilot.starpilot.ui.models_compact.gui_app.texture"), \
         mock.patch("openpilot.starpilot.ui.models_compact.gui_app.push_widget"), \
         mock.patch("openpilot.starpilot.ui.models_compact.BigDialog"), \
         mock.patch("openpilot.starpilot.ui.models_compact.BigConfirmationDialog") as confirm:
      owner._action(page, "download", "missing")
      session.model_manager_action.assert_not_called()
      callback = confirm.call_args.args[2]
      session.model_manager_snapshot.return_value = {**self.data, "isOnroad": True}
      callback()
      session.model_manager_action.assert_not_called()

  def test_randomizer_disables_manual_selection_but_keeps_favorites_independent(self):
    randomized = {**self.data, "randomizer": True}
    self.assertIsNone(model_profile_request(randomized, "small", "small"))
    self.assertIsNone(model_profile_request(randomized, "big", ""))
    self.assertTrue(model_action_allowed(randomized, "preferences", self.small))
    self.assertTrue(model_action_allowed(randomized, "exclusion", self.small))
    rows = model_page(ModelStatus(BUNDLED_CURRENT, None, None, ModelHealth.UNAVAILABLE, False, None, None), randomized).rows
    self.assertTrue(all(not row.available for row in rows[1:3]))
    self.assertEqual(rows[1].reason, "Randomizer selects at the next start")

  def test_native_preferences_dispatch_and_recheck_vehicle_state(self):
    session = mock.Mock()
    session.model_manager_snapshot.return_value = self.data
    owner = ModelsCompact(session)
    page = cast(_ModelsPage, SimpleNamespace())
    with mock.patch("openpilot.starpilot.ui.models_compact.gui_app.get_active_widget", return_value=page), \
         mock.patch("openpilot.starpilot.ui.models_compact.gui_app.push_widget"), \
         mock.patch("openpilot.starpilot.ui.models_compact.BigDialog"), mock.patch.object(owner, "_populate"):
      owner._action(page, "randomizer")
      session.model_manager_action.assert_called_with("preferences", {"randomizer": True})
      owner._action(page, "exclusion", "small")
      session.model_manager_action.assert_called_with("preferences", {"blacklistedModels": ["small"]})
      self.small["blacklisted"] = True
      self.big["blacklisted"] = True
      owner._action(page, "exclusion", "small")
      session.model_manager_action.assert_called_with("preferences", {"blacklistedModels": ["big"]})
      session.model_manager_action.reset_mock()
      session.model_manager_snapshot.return_value = {**self.data, "isOnroad": True}
      owner._action(page, "randomizer")
      owner._action(page, "exclusion", "small")
      session.model_manager_action.assert_not_called()
      owner._action(page, "preferences", "small")
      session.model_manager_action.assert_called_with("preferences", {"userFavorites": ["big", "small"]})


if __name__ == "__main__":
  unittest.main()
