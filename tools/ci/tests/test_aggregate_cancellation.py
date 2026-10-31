from pathlib import Path
import re
import unittest


# Pull requests into Honda-PTM-Testing skip the custom pytest catalog; every other event runs it.
FULL_SUITE = "!(github.event_name == 'pull_request' && github.base_ref == 'Honda-PTM-Testing')"


class AggregateCancellationTests(unittest.TestCase):
  def test_complete_catalogs_remain_mandatory_unless_workflow_cancelled(self):
    workflow = Path(__file__).parents[3].joinpath('.github/workflows/tests.yaml').read_text()
    for name, needs, command, scope in (
        ('custom_pytest_complete', 'custom_pytest', 'custom_pytest_shards aggregate', FULL_SUITE),
        ('aol_lifecycle_complete', 'aol_lifecycles', 'lifecycle_shards.py ci-results/aol-lifecycles', None)):
      with self.subTest(job=name):
        job = re.search(r'^  ' + name + r':\n(.*?)(?=^  [a-z_]+:|\Z)', workflow, re.M | re.S)
        self.assertIsNotNone(job)
        body = job.group(1)
        self.assertIn('    needs: ' + needs + '\n', body)
        guard = re.search(r'^    if: (.+)$', body, re.M).group(1)
        self.assertEqual(guard, '${{ always() && !cancelled()' + (f' && {scope}' if scope else '') + ' }}')
        self.assertIn(command, body)
        self.assertNotIn('continue-on-error', body)
        if scope:
          # The shards and their aggregate share one scope, so shards can never run without the aggregate.
          shards = re.search(r'^  ' + needs + r':\n(.*?)(?=^  [a-z_]+:|\Z)', workflow, re.M | re.S).group(1)
          self.assertEqual(re.search(r'^    if: (.+)$', shards, re.M).group(1), '${{ ' + scope + ' }}')
        # Failure, timeout or an individually missing shard must still reach the
        # unmodified fail-closed aggregate whenever the workflow is not cancelled.
        for upstream in ('success', 'failure', 'skipped', 'cancelled'):
          for workflow_cancelled in (False, True):
            for full_suite in ((False, True) if scope else (True,)):
              with self.subTest(upstream=upstream, workflow_cancelled=workflow_cancelled, full_suite=full_suite):
                expression = guard.removeprefix('${{ ').removesuffix(' }}')
                if scope:
                  expression = expression.replace(scope, str(full_suite))
                expression = expression.replace('always()', 'True').replace('cancelled()', str(workflow_cancelled))
                expression = expression.replace('&&', 'and').replace('!', 'not ')
                self.assertEqual(eval(expression, {'__builtins__': {}}), full_suite and not workflow_cancelled)
