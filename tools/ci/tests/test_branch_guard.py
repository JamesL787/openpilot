import unittest

from tools.ci.branch_guard import CLEAN, STABLE, STAGE, TESTING, violations

REPO = 'RiskyBiscuit-arc/openpilot'
FORK = 'someone/openpilot'


class TestBranchGuard(unittest.TestCase):
  def test_promotions_go_one_step_at_a_time(self):
    self.assertEqual(violations(STAGE, TESTING, REPO, REPO), [])
    self.assertEqual(violations(STABLE, STAGE, REPO, REPO), [])
    for base, head in ((STABLE, TESTING), (STABLE, 'wifi-power-save'), (STAGE, 'wifi-power-save'), (STAGE, STABLE)):
      with self.subTest(base=base, head=head):
        self.assertEqual(len(violations(base, head, REPO, REPO)), 1)

  def test_promotion_from_a_fork_with_the_same_name_is_refused(self):
    self.assertEqual(len(violations(STAGE, TESTING, FORK, REPO)), 1)
    self.assertEqual(len(violations(STABLE, STAGE, FORK, REPO)), 1)

  def test_testing_takes_feature_branches_but_nothing_flows_back(self):
    self.assertEqual(violations(TESTING, 'wifi-power-save', REPO, REPO), [])
    self.assertEqual(violations(TESTING, 'wifi-power-save', FORK, REPO), [])
    for head in (STAGE, STABLE, CLEAN):
      with self.subTest(head=head):
        self.assertEqual(len(violations(TESTING, head, REPO, REPO)), 1)

  def test_agent_prefixed_branches_are_refused_into_testing(self):
    for head in ('claude/project-thread-ja9lwc', 'Codex/fix', 'copilot/x'):
      with self.subTest(head=head):
        self.assertEqual(len(violations(TESTING, head, REPO, REPO)), 1)

  def test_other_bases_are_not_this_checks_business(self):
    self.assertEqual(violations('wifi-power-save', 'claude/x', REPO, REPO), [])
    self.assertEqual(violations(CLEAN, 'clean-sync', REPO, REPO), [])


if __name__ == '__main__':
  unittest.main()
