import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

CARD = Path(__file__).resolve().parents[1] / "assets" / "mobile" / "js" / "components" / "GalaxyToggleCard.js"

HARNESS = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const confirms = [], writes = [];
let answer = false;
const ctx = { console, FavoritesEditor: {}, ScreenBrightnessControl: {}, window: { confirm: () => true }, showSnackbar: () => {},
  GalaxyConfirm: async (options) => { confirms.push(options.title); return answer },
  api: { updateParam: async (data) => { writes.push(data); return { updated: { [data.key]: data.value } } } } };
vm.createContext(ctx);
const load = (file, expose) => vm.runInContext(fs.readFileSync(file, "utf8").replace(/^import[\s\S]*?from [^\n]+\n/gm, "")
  .replace(/export /g, "") + "\n" + expose, ctx);
load(process.env.PARAMS, "");
load(process.env.CARD, "this.card = GalaxyToggleCard; this.confirmation = starpilotAutoUploadConfirmation");
const blocked = { DeviceManagement: true, NoUploads: true, DisableOnroadUploads: true, AlwaysAllowUploads: false };
const title = (key, next, values) => (ctx.confirmation(key, next, values) || {}).title || null;
const commit = async (key, next, values, yes) => {
  answer = yes;
  const card = { param: { key, label: key }, value: !next, values, locked: false, updating: false, lastLabel: "",
    $emit: () => {}, rollback: () => {} };
  await ctx.card.methods.commit.call(card, next);
};
(async () => {
  const result = {
    enableUnblocked: title("StarpilotAutoEnabled", true, {}),
    enableAlreadyBlocked: title("StarpilotAutoEnabled", true, blocked),
    enableWithAlwaysAllow: title("StarpilotAutoEnabled", true, { ...blocked, AlwaysAllowUploads: true }),
    disableAuto: title("StarpilotAutoEnabled", false, {}),
    uploadsOnWithAuto: title("NoUploads", false, { StarpilotAutoEnabled: true }),
    alwaysAllowWithAuto: title("AlwaysAllowUploads", true, { StarpilotAutoEnabled: true }),
    deviceSettingsOffWithAuto: title("DeviceManagement", false, { StarpilotAutoEnabled: true }),
    allUploadsOffWithAuto: title("DisableOnroadUploads", false, { StarpilotAutoEnabled: true }),
    uploadsOnWithoutAuto: title("NoUploads", false, { StarpilotAutoEnabled: false }),
  };
  await commit("StarpilotAutoEnabled", true, {}, false);
  result.writesAfterCancel = writes.length;
  await commit("StarpilotAutoEnabled", true, {}, true);
  await commit("NoUploads", false, { StarpilotAutoEnabled: true }, true);
  result.writes = writes.map((w) => [w.key, w.value]);
  result.confirms = confirms.length;
  console.log(JSON.stringify(result));
})().catch((error) => { console.error(error); process.exit(1) });
"""


@pytest.fixture(scope="module")
def result():
  node = shutil.which("node")
  if node is None:
    pytest.skip("node is not installed")
  output = subprocess.run([node, "-e", HARNESS], env={**os.environ, "CARD": str(CARD), "PARAMS": str(CARD.parents[1] / "params.js")}, capture_output=True, text=True, timeout=30)
  assert output.returncode == 0, output.stderr
  return json.loads(output.stdout)


def test_turning_on_starpilot_auto_explains_the_upload_change(result):
  assert result["enableUnblocked"] == "Uploads will wait until parked"
  assert result["enableWithAlwaysAllow"] == "Uploads will wait until parked"
  assert result["enableAlreadyBlocked"] is None and result["disableAuto"] is None


def test_reopening_uploads_while_starpilot_auto_is_on_warns(result):
  warning = "Allow uploads while driving?"
  assert result["uploadsOnWithAuto"] == warning
  assert result["alwaysAllowWithAuto"] == warning
  assert result["deviceSettingsOffWithAuto"] == warning
  assert result["allUploadsOffWithAuto"] is None, "stopping all uploads keeps them off while driving"
  assert result["uploadsOnWithoutAuto"] is None


def test_cancel_writes_nothing_and_confirm_writes_the_setting(result):
  assert result["writesAfterCancel"] == 0
  assert result["writes"] == [["StarpilotAutoEnabled", True], ["NoUploads", False]]
  assert result["confirms"] == 3
