"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
import json
import math
import os
from collections.abc import Callable
import pyray as rl

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.ui_state import ui_state
from opendbc.sunnypilot.car.honda.values_ext import HondaFlagsSP
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.sunnypilot.lib.utils import NoElideButtonAction
from openpilot.system.ui.sunnypilot.widgets.list_view import ListItemSP, toggle_item_sp, option_item_sp
from openpilot.system.ui.sunnypilot.widgets.tree_dialog import TreeOptionDialog, TreeFolder, TreeNode
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.network import NavButton
from openpilot.system.ui.widgets.scroller_tici import Scroller

TORQUE_VERSIONS_PATH = os.path.join(BASEDIR, "sunnypilot", "selfdrive", "controls", "lib", "latcontrol_torque_versions.json")


class TorqueSettingsLayout(Widget):
  def __init__(self, back_btn_callback: Callable):
    super().__init__()
    self._back_button = NavButton(tr("Back"))
    self._back_button.set_click_callback(back_btn_callback)
    self._torque_version_dialog: TreeOptionDialog | None = None
    self._honda_firestar_dialog: TreeOptionDialog | None = None
    self.cached_torque_versions = {}
    self._load_versions()
    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def _load_versions(self):
    with open(TORQUE_VERSIONS_PATH) as f:
      self.cached_torque_versions = json.load(f)

  def _initialize_items(self):
    self._torque_control_versions = ListItemSP(
      title=tr("Torque Control Tune Version"),
      description="Select the version of Torque Control Tune to use.",
      action_item=NoElideButtonAction(tr("SELECT")),
      callback=self._show_torque_version_dialog,
    )
    self._honda_firestar_tune = ListItemSP(
      title=tr("Honda StarPilot Tune"),
      description="Select the Honda StarPilot stock or Firestar (5B) tune variant.",
      action_item=NoElideButtonAction(tr("SELECT")),
      callback=self._show_honda_firestar_dialog,
    )
    self._self_tune_toggle = toggle_item_sp(
      param="LiveTorqueParamsToggle",
      title=lambda: tr("Self-Tune"),
      description=lambda: tr("Enables self-tune for Torque lateral control for platforms that do not use " +
                             "Torque lateral control by default."),
    )
    self._relaxed_tune_toggle = toggle_item_sp(
      param="LiveTorqueParamsRelaxedToggle",
      title=lambda: tr("Less Restrict Settings for Self-Tune (Beta)"),
      description=lambda: tr("Less strict settings when using Self-Tune. This allows torqued to be more " +
                             "forgiving when learning values."),
    )
    self._custom_tune_toggle = toggle_item_sp(
      param="CustomTorqueParams",
      title=lambda: tr("Enable Custom Tuning"),
      description=lambda: tr("Enables custom tuning for Torque lateral control. " +
                             "Modifying Lateral Acceleration Factor and Friction below will override the offline values " +
                             "indicated in the YAML files within \"opendbc/car/torque_data\". " +
                             "The values will also be used live when \"Manual Real-Time Tuning\" toggle is enabled."),
    )
    self._torque_prams_override_toggle = toggle_item_sp(
      param="TorqueParamsOverrideEnabled",
      title=lambda: tr("Manual Real-Time Tuning"),
      description=lambda: tr("Enforces the torque lateral controller to use the fixed values instead of the learned " +
                             "values from Self-Tune. Enabling this toggle overrides Self-Tune values."),
    )
    self._torque_lat_accel_factor = option_item_sp(
      title=lambda: tr("Lateral Acceleration Factor"),
      param="TorqueParamsOverrideLatAccelFactor",
      description="",
      min_value=1,
      max_value=500,
      value_change_step=1,
      label_callback=(lambda x: f"{x/100} m/s^2"),
      use_float_scaling=True
    )

    self._torque_friction = option_item_sp(
      title=lambda: tr("Friction"),
      param="TorqueParamsOverrideFriction",
      description="",
      min_value=1,
      max_value=100,
      value_change_step=1,
      label_callback=(lambda x: f"{x/100}"),
      use_float_scaling=True
    )

    items = [
      self._torque_control_versions,
      self._honda_firestar_tune,
      self._self_tune_toggle,
      self._relaxed_tune_toggle,
      self._custom_tune_toggle,
      self._torque_prams_override_toggle,
      self._torque_lat_accel_factor,
      self._torque_friction,
    ]
    return items

  def _update_state(self):
    super()._update_state()
    if not ui_state.params.get_bool("LiveTorqueParamsToggle"):
      ui_state.params.remove("LiveTorqueParamsRelaxedToggle")
      self._relaxed_tune_toggle.action_item.set_state(False)
    self._self_tune_toggle.action_item.set_enabled(ui_state.is_offroad())
    self._relaxed_tune_toggle.action_item.set_enabled(ui_state.is_offroad() and self._self_tune_toggle.action_item.get_state())
    self._custom_tune_toggle.action_item.set_enabled(ui_state.is_offroad())
    custom_tune_enabled = self._custom_tune_toggle.action_item.get_state()
    self._torque_prams_override_toggle.set_visible(custom_tune_enabled)
    self._torque_lat_accel_factor.set_visible(custom_tune_enabled)
    self._torque_friction.set_visible(custom_tune_enabled)

    self._torque_prams_override_toggle.action_item.set_enabled(ui_state.is_offroad())
    sliders_enabled = self._torque_prams_override_toggle.action_item.get_state() or ui_state.is_offroad()
    self._torque_lat_accel_factor.action_item.set_enabled(sliders_enabled)
    self._torque_friction.action_item.set_enabled(sliders_enabled)

    title_text = tr("Real-Time & Offline") if ui_state.params.get("TorqueParamsOverrideEnabled") else tr("Offline Only")
    self._torque_lat_accel_factor.set_title(lambda: tr("Lateral Acceleration Factor") + " (" + title_text + ")")
    self._torque_friction.set_title(lambda: tr("Friction") + " (" + title_text + ")")
    self._torque_control_versions.action_item.set_value(self._get_current_torque_version_label())
    self._honda_firestar_tune.action_item.set_value(self._get_current_honda_firestar_label())
    torque_version = self._get_current_torque_version()
    is_honda_eps_modified = (
      ui_state.CP is not None and
      ui_state.CP_SP is not None and
      bool(ui_state.CP_SP.flags & HondaFlagsSP.EPS_MODIFIED.value)
    )
    self._honda_firestar_tune.set_visible(
      ui_state.is_offroad() and
      is_honda_eps_modified and
      ui_state.params.get_bool("EnforceTorqueControl") and
      math.isclose(torque_version or 0.0, 2.0, rel_tol=1e-5)
    )

  def _render(self, rect):
    self._back_button.set_position(self._rect.x, self._rect.y + 20)
    self._back_button.render()
    # subtract button
    content_rect = rl.Rectangle(rect.x, rect.y + self._back_button.rect.height + 40, rect.width, rect.height - self._back_button.rect.height - 40)
    self._scroller.render(content_rect)

  def show_event(self):
    self._scroller.show_event()

  def _get_current_torque_version(self):
    current_val_bytes = ui_state.params.get("TorqueControlTune")
    if current_val_bytes is None:
      return None

    try:
      return float(current_val_bytes)
    except (ValueError, TypeError):
      return None

  def _get_current_torque_version_label(self):
    current_val = self._get_current_torque_version()
    if current_val is None:
      return tr("Default")

    try:
      for label, info in self.cached_torque_versions.items():
        if math.isclose(float(info["version"]), current_val, rel_tol=1e-5):
          return label
    except (ValueError, KeyError):
      pass

    return tr("Default")

  def _get_current_honda_firestar_label(self):
    if not ui_state.params.get_bool("HondaTorqueFirestarTune"):
      return tr("Stock tune")
    return tr("Firestar Tune")

  def _show_torque_version_dialog(self):
    options_map = {}
    for label, info in self.cached_torque_versions.items():
      try:
        options_map[label] = float(info["version"])
      except (ValueError, KeyError):
        pass

    # Sort options by label in descending order
    sorted_labels = sorted(options_map.keys(), key=lambda k: options_map[k], reverse=True)

    nodes = [TreeNode(tr("Default"))]
    for label in sorted_labels:
      nodes.append(TreeNode(label))

    folders = [TreeFolder("", nodes)]

    current_label = self._get_current_torque_version_label()

    def handle_selection(result: int):
      if result == DialogResult.CONFIRM and self._torque_version_dialog:
        selected_ref = self._torque_version_dialog.selection_ref
        if selected_ref == tr("Default"):
          ui_state.params.remove("TorqueControlTune")
        elif selected_ref in options_map:
          ui_state.params.put("TorqueControlTune", options_map[selected_ref])
      self._torque_version_dialog = None

    self._torque_version_dialog = TreeOptionDialog(
      tr("Select Torque Control Tune Version"),
      folders,
      current_ref=current_label,
      option_font_weight=FontWeight.UNIFONT,
      on_exit=handle_selection,
    )
    gui_app.push_widget(self._torque_version_dialog)

  def _show_honda_firestar_dialog(self):
    nodes = [TreeNode(tr("Stock tune")), TreeNode(tr("Firestar Tune"))]
    folders = [TreeFolder("", nodes)]
    current_label = self._get_current_honda_firestar_label()

    def handle_selection(result: int):
      if result == DialogResult.CONFIRM and self._honda_firestar_dialog:
        selected_ref = self._honda_firestar_dialog.selection_ref
        if selected_ref == tr("Stock tune"):
          ui_state.params.remove("HondaTorqueFirestarTune")
        elif selected_ref == tr("Firestar Tune"):
          ui_state.params.put("HondaTorqueFirestarTune", "1")
      self._honda_firestar_dialog = None

    self._honda_firestar_dialog = TreeOptionDialog(
      tr("Select Honda StarPilot Tune"),
      folders,
      current_ref=current_label,
      option_font_weight=FontWeight.UNIFONT,
      on_exit=handle_selection,
    )
    gui_app.push_widget(self._honda_firestar_dialog)
