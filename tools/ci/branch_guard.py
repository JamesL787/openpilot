"""Enforce the Honda-PTM branch flow on pull requests (docs/BRANCH_WORKFLOW.md).

Rulesets can protect a branch, but they cannot say which branch a pull request comes from. This check does:
  - Honda-PTM-Stage takes pull requests only from Honda-PTM-Testing,
  - Honda-PTM-Stable takes pull requests only from Honda-PTM-Stage,
  - Honda-PTM-Testing takes no pull request from Stage, Stable or Clean (changes move one way), and
    no branch named with a tool or agent prefix such as `claude/`,
  - Honda-PTM-Clean is checked by tools/night_star_port/check_clean_branch.py against Honda-PTM-Stable.

Promotion pull requests must come from this repository, not from a fork.

usage: branch_guard.py <base> <head> <head-repo> <repo>
"""
import sys

STABLE, STAGE, TESTING, CLEAN = 'Honda-PTM-Stable', 'Honda-PTM-Stage', 'Honda-PTM-Testing', 'Honda-PTM-Clean'
LONG_LIVED = (STABLE, STAGE, TESTING, CLEAN)
PROMOTES_FROM = {STAGE: TESTING, STABLE: STAGE}
AGENT_PREFIXES = ('claude/', 'codex/', 'copilot/', 'cursor/', 'gemini/')


def violations(base, head, head_repo, repo):
  if base in PROMOTES_FROM:
    source = PROMOTES_FROM[base]
    if head != source or head_repo != repo:
      return [f'{base} takes pull requests only from {repo}:{source}, not {head_repo}:{head}. '
              f'Open the change against {TESTING} and promote it.']
    return []
  if base == TESTING:
    if head in LONG_LIVED and head_repo == repo:
      return [f'{head} does not merge back into {TESTING}: changes move Testing -> Stage -> Stable only. '
              f'Branch the fix off {TESTING} instead.']
    if head.lower().startswith(AGENT_PREFIXES):
      return [f'branch {head} uses a tool or agent prefix; name it after the work (for example wifi-power-save)']
  return []


def main(argv):
  if len(argv) != 4:
    sys.exit(__doc__)
  found = violations(*argv)
  for line in found:
    print(f'::error::{line}')
  print(f'{argv[2]}:{argv[1]} -> {argv[0]}: ' + ('FAIL' if found else 'ok'))
  return 1 if found else 0


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
