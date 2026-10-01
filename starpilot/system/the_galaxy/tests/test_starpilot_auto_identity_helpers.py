"""Covers assets/mobile/js/components/starpilot_auto_identity_helpers.js through node."""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

HELPERS_PATH = Path(__file__).resolve().parent.parent / "assets" / "mobile" / "js" / "components" / "starpilot_auto_identity_helpers.js"
MIN_NODE_MAJOR = 23

HARNESS = f'''
import * as helpers from {json.dumps(HELPERS_PATH.as_uri())}
const run = new Function(...Object.keys(helpers), process.env.STARPILOT_AUTO_HELPER_SNIPPET)
process.stdout.write(JSON.stringify(run(...Object.values(helpers)) ?? null))
'''


def evaluate(snippet):
  node = shutil.which("node")
  if node is None:
    pytest.skip("node is not installed")
  version = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
  if int(version.lstrip("v").split(".")[0]) < MIN_NODE_MAJOR:
    pytest.skip(f"node {version} cannot import a bare .js ES module; need v{MIN_NODE_MAJOR}+")
  result = subprocess.run([node, "--input-type=module"], input=HARNESS, env={**os.environ, "STARPILOT_AUTO_HELPER_SNIPPET": snippet},
                          capture_output=True, text=True, timeout=60)
  assert result.returncode == 0, result.stderr
  return json.loads(result.stdout)


def test_identity_states():
  states = evaluate('''return [
    describeIdentity(null).title,
    describeIdentity({installed: false}).title,
    describeIdentity({installed: false, expired: true}).tone,
    describeIdentity({installed: false, error: "key readable by others"}).text,
    describeIdentity({installed: true, expires: "2026-12-23T22:48:29+00:00", days_left: 90, warning: ""}),
    describeIdentity({installed: true, expires: "2026-12-23T22:48:29+00:00", days_left: 1, warning: "soon"}).title,
  ]''')
  assert states[:4] == ["Checking…", "Not installed", "danger", "key readable by others"]
  assert states[4] == {"tone": "ok", "title": "Installed", "text": "Valid until 2026-12-23 (90 days left)."}
  assert states[5] == "Expires in 1 day"


def test_job_progress_and_results():
  jobs = evaluate('''return [
    describeJob({state: "idle"}),
    describeJob({state: "running", stage: "downloading", downloaded: 5 * 1048576, total: 50 * 1048576}).text,
    describeJob({state: "running", stage: "verifying"}).text,
    describeJob({state: "done", message: "Identity installed; valid until 2026-12-23"}),
    describeJob({state: "failed", error: "Not an APK"}).text,
    describeJob({state: "done", finished: 1000, message: "ok"}, 1100) !== null,
    describeJob({state: "done", finished: 1000, message: "ok"}, 1200),
    describeJob({state: "failed", finished: 1000, error: "x"}, 99999).text,
  ]''')
  assert jobs[0] is None
  assert jobs[1] == "Downloading to the comma · 5.0 of 50 MB…"
  assert jobs[2] == "Verifying…"
  assert jobs[3] == {"tone": "ok", "running": False, "text": "Identity installed; valid until 2026-12-23"}
  assert jobs[4] == "Not an APK"
  assert jobs[5] is True and jobs[6] is None and jobs[7] == "x"  # success fades after 2 minutes, failures stay


def test_upload_label_and_file_types():
  assert evaluate('return [uploadLabel({installed: false}), uploadLabel({installed: true}), uploadLabel({expired: true})]') == \
    ["Install from File", "Replace from File", "Replace from File"]
  assert evaluate('return ["a.XAPK", "b.apk", "c.apkm", "d.zip", ""].map(acceptsFile)') == [True, True, True, False, False]


def test_recommended_progress():
  assert evaluate('return ["resolving", "checking_package", "unpacking"].map(stage => describeJob({state: "running", stage}).text)') == [
    "Getting the recommended version…", "Checking the download…", "Preparing the file…",
  ]
