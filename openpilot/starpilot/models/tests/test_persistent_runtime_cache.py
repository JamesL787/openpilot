"""Persistent startup cache selection; not GPU or road qualification."""
from pathlib import Path
from unittest.mock import patch

import pytest

from openpilot.starpilot.models.runtime_bridge import runtime


@pytest.mark.skipif(runtime.PERSONAL_VENDORED_RUNTIME, reason="personal branch: the legacy runtime bridge is inert (runtime_bridge.PERSONAL_VENDORED_RUNTIME)")
@pytest.mark.parametrize("role", ["driving", "monitoring"])
def test_inference_cache_survives_reboot_without_changing_role_isolation(role):
  selected = {"role": role}
  with (patch("openpilot.common.hardware.AGNOS", True),
        patch.object(runtime, "_selection", None),
        patch.object(runtime, "_verify_policy") as verify,
        patch.object(runtime, "activate", return_value=selected) as activate):
    assert runtime.prepare(role) is selected
    verify.assert_called_once()
    activate.assert_called_once_with(runtime.BUNDLE, runtime.MANIFEST_SHA256,
                                     runtime.LEGACY_REVISION, role, Path("/data/starpilot-model-runtime"))
    assert runtime.prepare(role) is selected
    assert activate.call_count == 1


def test_host_does_not_create_device_cache():
  with (patch("openpilot.common.hardware.AGNOS", False),
        patch.object(runtime, "_selection", None),
        patch.object(runtime, "activate", side_effect=AssertionError("must not touch device cache"))):
    assert runtime.prepare("driving") is None
