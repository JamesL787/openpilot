#!/usr/bin/env python3
"""Stage the pinned ARM64 browser under /data; never install packages into AGNOS."""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

ROOT = Path('/data/arabesque-firefox')
BROWSER_UID = 61234


def report(message):
  print(message, flush=True)


def verify(path, package):
  algorithm = 'sha512' if 'sha512' in package else 'sha256'
  with path.open('rb') as stream:
    digest = hashlib.file_digest(stream, algorithm).hexdigest()
  if path.stat().st_size != package['size'] or digest != package[algorithm]:
    raise ValueError(f'Package checksum mismatch: {package["name"]}')


def download(package, cache):
  path = cache / package['name']
  if not path.exists():
    partial = path.with_suffix('.partial')
    try:
      with urllib.request.urlopen(package['url'], timeout=30) as response, partial.open('wb') as target:
        if not response.url.startswith('https://'):
          raise ValueError('Refusing an insecure browser package redirect')
        remaining = package['size']
        while block := response.read(min(1024 * 1024, remaining + 1)):
          remaining -= len(block)
          if remaining < 0:
            raise ValueError('Browser package exceeds pinned size')
          target.write(block)
          label = 'Firefox' if package['name'].startswith('firefox-') else 'browser libraries'
          report(f'Downloading {label}… {100 * (package["size"] - remaining) // package["size"]}%')
      verify(partial, package)
      partial.rename(path)
    finally:
      partial.unlink(missing_ok=True)
  verify(path, package)
  return path


def unpack(path, destination):
  if path.suffix == '.deb':
    subprocess.run(['/usr/bin/dpkg-deb', '--extract', str(path), str(destination)], check=True, timeout=30)
  else:
    with tarfile.open(path) as archive:
      archive.extractall(destination, filter='data')


def prepare():
  manifest = json.loads(Path(__file__).with_name('runtime.json').read_text())
  if os.geteuid() != 0 or platform.machine() != 'aarch64' or Path('/VERSION').read_text().strip() != manifest['agnos']:
    raise RuntimeError('Prepare this runtime as root on ARM64 AGNOS 19.8.1')
  for path in (ROOT, ROOT / 'runtime', ROOT / 'state', ROOT / 'packages'):
    if path.is_symlink():
      raise RuntimeError(f'Refusing symlink: {path}')
  if ROOT.exists() and (ROOT.stat().st_uid != 0 or ROOT.stat().st_mode & 0o022):
    raise RuntimeError('Unsafe browser directory ownership')
  ROOT.mkdir(mode=0o755, exist_ok=True)
  with (ROOT / '.prepare.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    prepare_locked(manifest)


def prepare_locked(manifest):
  cache = ROOT / 'packages'
  if (ROOT / 'runtime').exists():
    raise RuntimeError('Runtime already exists; stop and review an update separately. The profile is never replaced.')
  try:
    pwd.getpwuid(BROWSER_UID)
  except KeyError:
    pass
  else:
    raise RuntimeError(f'UID {BROWSER_UID} is already assigned')
  for entry in Path('/proc').iterdir():
    if entry.name.isdigit():
      try:
        if entry.stat().st_uid == BROWSER_UID:
          raise RuntimeError(f'UID {BROWSER_UID} already has running processes')
      except FileNotFoundError:
        pass
  if shutil.disk_usage('/data').free < 6 * 1024**3:
    raise RuntimeError('At least 6 GiB free on /data is required to prepare Firefox')
  active = subprocess.check_output(['systemctl', '--no-pager', '--plain', '--no-legend', 'list-units', 'arabesque-firefox-*'], text=True)
  own_unit = next((Path(line[3:]).name for line in Path('/proc/self/cgroup').read_text().splitlines() if line.startswith('0::')), '')
  if any(line.split()[0] != own_unit for line in active.splitlines() if line.split()):
    raise RuntimeError('Close all Firefox sessions before preparing the runtime')
  # A hard stop can interrupt extraction; only this root-owned staging area is disposable.
  for path in ROOT.glob('.prepare-*'):
    if path.is_symlink():
      path.unlink()
    elif path.is_dir():
      shutil.rmtree(path)
  state = ROOT / 'state'
  if state.exists() and (state.stat().st_uid != BROWSER_UID or state.stat().st_mode & 0o077):
    raise RuntimeError('Unexpected browser state owner or permissions')
  if not state.exists():
    state.mkdir(mode=0o700)
    os.chown(state, BROWSER_UID, BROWSER_UID)
  cache.mkdir(mode=0o700, exist_ok=True)
  if cache.stat().st_uid != 0 or cache.stat().st_mode & 0o077:
    raise RuntimeError('The browser package cache must be owned by root with mode 0700')
  with tempfile.TemporaryDirectory(prefix='.prepare-', dir=ROOT) as temporary:
    staging = Path(temporary) / 'runtime'
    staging.mkdir()
    for index, package in enumerate(manifest['packages'], 1):
      report(f'Preparing Firefox ({index}/{len(manifest["packages"])})…')
      archive = download(package, cache)
      if archive.is_symlink() or archive.stat().st_uid != 0 or archive.stat().st_mode & 0o022:
        raise RuntimeError('Unsafe browser package cache file')
      report('Unpacking Firefox…' if package['name'].startswith('firefox-') else 'Preparing browser libraries…')
      unpack(archive, staging)
    schemas = staging / 'usr/share/glib-2.0/schemas'
    for source in Path('/usr/share/glib-2.0/schemas').glob('*.xml'):
      if not (schemas / source.name).exists():
        shutil.copyfile(source, schemas / source.name)
    subprocess.run(['/usr/bin/glib-compile-schemas', '--strict', str(schemas)], check=True, timeout=10)
    distribution = staging / 'firefox/distribution'
    distribution.mkdir(exist_ok=True)
    (distribution / 'policies.json').write_text(json.dumps({'policies': {
      'DisableAppUpdate': True, 'DontCheckDefaultBrowser': True, 'DisableTelemetry': True, 'DisableFirefoxStudies': True,
    }}))
    for name in ('empty', 'devices', 'devices/shm'):
      (staging / 'isolation' / name).mkdir(parents=True, exist_ok=True)
    for name in ('null', 'zero', 'random', 'urandom'):
      (staging / 'isolation/devices' / name).touch()
    (staging / 'ready.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for path in (staging, *staging.rglob('*')):
      if not path.is_symlink():
        os.chown(path, 0, 0)
        path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
    (ROOT / '.isolation-probe').write_text('This file must be hidden from the Firefox worker.\n')
    staging.rename(ROOT / 'runtime')
  report('Firefox is prepared. Starting the browser…')


if __name__ == '__main__':
  prepare()
