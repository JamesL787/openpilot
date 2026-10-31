"""Driving Model page actions on the native shell: the profile and download dialogs and the manager jobs they start.

`session` is runtime_app's StarShellSession; these read and write its model manager and settings state."""

from openpilot.starpilot.ui.models_state import (model_action_allowed, model_download_choices, model_profile_choices,
                                                 model_profile_request)
from openpilot.starpilot.ui.settings_state import Destination
from openpilot.starpilot.ui.shell import ShellMode


def _on_model_page(session) -> bool:
  return session._mode == ShellMode.SETTINGS and session.selected == Destination.DRIVING_MODEL


def open_model_page(session, page: str) -> bool:
  """Opens a Driving Model row's page; False when it refused and left the shell's snapshot as it was."""
  if page in ("models:small", "models:big"):
    return _open_profile(session, page.split(":", 1)[1])
  if page == "models:download":
    return _open_download(session)
  if page in ("models:download_all", "models:cancel", "models:refresh_manifest"):
    model_download(session, page.split(":", 1)[1], {})
  return True


def _open_profile(session, profile: str) -> bool:
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.widgets import DialogResult
  from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
  manager = session.model_manager_snapshot()
  choices = dict(model_profile_choices(manager, profile))
  if not choices:
    checking = any(m.get("checking") for m in manager.get("models", ()))
    session._unavailable("still checking installed models; try again" if checking else
                         "no installed Small model yet; use Download a model")
    return False
  current = manager["activeSmallModel" if profile == "small" else "activeBigModel"]
  current_label = next((label for label, model_id in choices.items() if model_id == current), "")

  def confirmed(result):
    if result != DialogResult.CONFIRM or not _on_model_page(session):
      return
    fresh = session.model_manager_snapshot()
    if fresh["activeSmallModel" if profile == "small" else "activeBigModel"] != current:
      session._unavailable("saved model changed; reopen the selection")
      return
    request = model_profile_request(fresh, profile, choices.get(dialog.selection, ""))
    if request is not None:
      try:
        session.model_manager_action("active", request)
      except (OSError, ValueError, RuntimeError) as error:
        session._unavailable(str(error))
    session._snapshot_cache = None

  dialog = MultiOptionDialog(f"Active {'Small' if profile == 'small' else 'Big'}", list(choices), current_label, callback=confirmed)
  gui_app.push_widget(dialog)
  return True


def _open_download(session) -> bool:
  from openpilot.system.ui.lib.application import gui_app
  from openpilot.system.ui.widgets import DialogResult
  from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
  downloads = dict(model_download_choices(session.model_manager_snapshot()))
  if not downloads:
    session._unavailable("no model left to download")
    return False

  def download(result):
    if result == DialogResult.CONFIRM and dialog.selection in downloads:
      model_download(session, "download", {"model": downloads[dialog.selection]})

  dialog = MultiOptionDialog("Download a model", list(downloads), "", callback=download)
  gui_app.push_widget(dialog)
  return True


def model_download(session, action: str, payload: dict) -> None:
  """Starts a manager download job after re-checking it against a fresh snapshot."""
  if not _on_model_page(session):
    return
  fresh = session.model_manager_snapshot()
  model = next((m for m in fresh.get("models", ()) if m.get("value") == payload["model"]), None) if "model" in payload else None
  downloads = dict(model_download_choices(fresh)).values()
  if (not model_action_allowed(fresh, action, model) or action == "download" and (model or {}).get("value") not in downloads or
      action == "download_all" and not downloads):
    session._unavailable("turn off the vehicle, then try again")
  else:
    try:
      session.model_manager_action(action, payload)
    except (OSError, ValueError, RuntimeError) as error:
      session._unavailable(str(error))
  session._snapshot_cache = None
