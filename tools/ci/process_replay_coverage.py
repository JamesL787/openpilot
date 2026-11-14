"""Account for replay inputs separately from test execution and vehicle qualification."""

import json
from pathlib import Path


# Honda is the supported brand, so its recordings are the vehicles under test. The Hyundai and Toyota recordings
# are kept as inputs for the brand-neutral processes only; no other brand's recording is replayed.
REQUIRED_REPLAY_LABELS = frozenset({"HONDA", "HONDA2"})
SHARED_PROCESS_INPUT_LABELS = frozenset({"HYUNDAI", "TOYOTA"})
EVIDENCE_LIMIT = ("Input accounting only. Brands outside opendbc.car.supported_brands start in dashcam mode and are not " +
                  "replayed as vehicles. This does not qualify the fleet.")


def replay_coverage(active_platforms, labels, suite_targets, *, full_test):
  labels = set(labels)
  recorded_brands = {label.lower() for label in labels}
  errors = []
  missing = set(active_platforms) - recorded_brands
  if full_test:
    absent_labels = (REQUIRED_REPLAY_LABELS | SHARED_PROCESS_INPUT_LABELS) - labels
    if absent_labels:
      errors.append(f"Required replay inputs missing: {sorted(absent_labels)}")
    unexpected = labels - REQUIRED_REPLAY_LABELS - SHARED_PROCESS_INPUT_LABELS
    if unexpected:
      errors.append(f"Replay inputs outside the supported scope: {sorted(unexpected)}")
    if missing:
      errors.append(f"Active brands missing unaccounted replay inputs: {sorted(missing)}")
  return {"schema_version": 1, "scope": "process_replay_input_inventory", "full_test": full_test,
          "recorded_input_labels": sorted(labels), "shared_process_input_labels": sorted(labels & SHARED_PROCESS_INPUT_LABELS),
          "active_platforms": active_platforms, "unrecorded_gaps": [], "errors": errors,
          "evidence_limit": EVIDENCE_LIMIT}


def write_coverage(report, destination, summary=None):
  destination = Path(destination)
  destination.parent.mkdir(parents=True, exist_ok=True)
  destination.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
  if summary:
    with Path(summary).open("a") as output:
      output.write("\n### Process replay input coverage\n\n")
      output.write(f"Full input inventory: {report['full_test']}; recorded inputs: {len(report['recorded_input_labels'])}.\n\n")
      for gap in report["unrecorded_gaps"]:
        output.write(f"- {gap['brand']} / {', '.join(gap['platforms'])}: **unrecorded**. {gap['reason']}\n")
        for suite, path in gap["required_source_native_suites"].items():
          output.write(f"  Required independent source/native check: {suite}: `{path}`.\n")
      for error in report["errors"]:
        output.write(f"- Coverage error: {error}\n")
      output.write(f"\n{report['evidence_limit']}\n")
