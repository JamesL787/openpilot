#!/usr/bin/env python3
"""Check that a clean branch is its base plus exactly the clean changes, and nothing else.

A clean branch (night-star7-clean, Honda-PTM-Clean) follows its base by merging: merge the base into
the clean branch, never rebase or force-push it. This check runs after each merge:
  - the base is fully merged (the clean branch contains its tip), and
  - `git diff base clean` changes exactly the paths in clean_branch_paths.txt, with the same status.

The clean changes put comma back as the default connect provider, drop Konik adoption, restore the
seatbelt check, and ship device binaries built with the clean params_keys.h. When a merge conflicts
on one of those binaries, rebuild them in Docker (tools/laptop_device_build) on the clean branch and
commit the result; never take the base's binaries.

usage: check_clean_branch.py <base-ref> <clean-ref>
"""
import subprocess
import sys
from pathlib import Path

MANIFEST = Path(__file__).with_name('clean_branch_paths.txt')


def git(*args):
  return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout


def main(base, clean):
  failures = []
  if subprocess.run(['git', 'merge-base', '--is-ancestor', base, clean]).returncode != 0:
    failures.append(f'{base} is not merged into {clean}: merge the base first')
  expected = {tuple(line.split(' ', 1)) for line in MANIFEST.read_text().splitlines() if line.strip()}
  actual = {tuple(line.split('\t', 1)) for line in git('diff', '--no-renames', '--name-status', base, clean).splitlines()}
  for status, path in sorted(actual - expected, key=lambda row: row[1]):
    failures.append(f'unexpected change: {status} {path}')
  for status, path in sorted(expected - actual, key=lambda row: row[1]):
    failures.append(f'missing clean change: {status} {path}')
  for failure in failures:
    print(failure)
  print(f'{clean} vs {base}: ' + ('FAIL' if failures else f'ok, {len(actual)} clean changes'))
  return 1 if failures else 0


if __name__ == '__main__':
  if len(sys.argv) != 3:
    sys.exit(__doc__)
  sys.exit(main(sys.argv[1], sys.argv[2]))
