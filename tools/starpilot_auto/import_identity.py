#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from openpilot.starpilot.system.starpilot_auto import apk_identity


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("--apk", type=Path, required=True, help="Starpilot Auto APK, XAPK or APKM")
  parser.add_argument("--output", type=Path, default=Path(".cache/starpilot_auto/identity"),
                      help="identity directory to write (a previous one is kept as <output>.previous)")
  args = parser.parse_args()
  try:
    files, metadata = apk_identity.extract_identity(args.apk.expanduser(), progress=lambda stage: print(f"{stage}…", flush=True))
    apk_identity.install_identity(files, metadata, args.output)
  except apk_identity.IdentityImportError as error:
    parser.exit(1, f"error: {error}\n")
  print(json.dumps({**metadata, "directory": str(args.output)}, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
