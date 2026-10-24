import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

GIT = ['git', '--no-optional-locks', '-c', 'gc.auto=0', '-c', 'maintenance.auto=false']

spec = importlib.util.spec_from_file_location('private_build_identity', Path(__file__).parents[1] / 'lifecycle_shards.py')
assert spec is not None and spec.loader is not None
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class BuildIdentityTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory()
    self.addCleanup(self.directory.cleanup)
    self.root = Path(self.directory.name)
    self.inventory_bytes = Path(__file__).parents[1].joinpath('lifecycle_build_outputs.json').read_bytes()
    self.inventory = json.loads(self.inventory_bytes)
    inventory_path = self.root / 'tools/ci/lifecycle_build_outputs.json'
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_bytes(self.inventory_bytes)
    for name in self.inventory:
      path = self.root / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_bytes(b'build output')
    for name in {'SConstruct', *[row['recipe'] for row in self.inventory.values()], 'opendbc_repo/native_input.h'}:
      path = self.root / name
      path.parent.mkdir(parents=True, exist_ok=True)
      path.write_text('source input\n')
    subprocess.run([*GIT, 'init', '-q'], cwd=self.root, check=True)
    subprocess.run([*GIT, 'add', '.'], cwd=self.root, check=True)
    subprocess.run([*GIT, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'Fixture'], cwd=self.root, check=True)

  def test_only_named_outputs_can_differ_with_identical_inputs(self):
    first = helper.build_identity(self.root)
    (self.root / 'msgq_repo/msgq/ipc_pyx.so').write_bytes(b'independent genuine build')
    second = helper.build_identity(self.root)
    self.assertTrue(helper.same_build_inputs(first, second))
    self.assertNotEqual(first['declared_outputs'], second['declared_outputs'])
    self.assertNotEqual(first, second)  # The per-job before/after guard still rejects an in-test mutation.

  def test_source_native_input_and_recipe_changes_are_denied(self):
    first = helper.build_identity(self.root)
    for name in ('opendbc_repo/native_input.h', 'SConstruct'):
      path = self.root / name
      original = path.read_bytes()
      path.write_bytes(b'changed source')
      self.assertFalse(helper.same_build_inputs(first, helper.build_identity(self.root)))
      path.write_bytes(original)

  def test_undeclared_input_path_is_pinned(self):
    first = helper.build_identity(self.root)
    path = self.root / 'opendbc_repo/undeclared.so'
    path.write_bytes(b'unregistered artifact')
    self.assertFalse(helper.same_build_inputs(first, helper.build_identity(self.root)))

  def test_missing_declared_artifact_is_denied(self):
    (self.root / 'msgq_repo/msgq/ipc_pyx.so').unlink()
    with self.assertRaises(ValueError):
      helper.build_identity(self.root)

  def test_nonoutput_symlink_target_is_pinned(self):
    path = self.root / 'opendbc_repo/input-link.h'
    path.symlink_to('native_input.h')
    subprocess.run([*GIT, 'add', '.'], cwd=self.root, check=True)
    subprocess.run([*GIT, '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'Symlink'],
                   cwd=self.root, check=True)
    first = helper.build_identity(self.root)
    path.unlink()
    path.symlink_to('other_source.h')
    self.assertFalse(helper.same_build_inputs(first, helper.build_identity(self.root)))

  def test_forged_or_stripped_provenance_is_denied(self):
    first = helper.build_identity(self.root)
    for field in ('inputs', 'declared_outputs'):
      forged = copy.deepcopy(first)
      del forged[field]
      with self.assertRaises(ValueError):
        helper.same_build_inputs(first, forged)
    forged = copy.deepcopy(first)
    forged['inputs']['output_inventory_sha256'] = 'f' * 64
    with self.assertRaises(ValueError):
      helper.same_build_inputs(first, forged)


if __name__ == '__main__':
  unittest.main()
