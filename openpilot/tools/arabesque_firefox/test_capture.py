"""Opt-in native check: run only under a disposable Xvfb, never a personal desktop."""

import ctypes as C
import importlib.util
import mmap
import os
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / 'selfdrive/ui/layouts/arabesque/tools'


def module(name):
  spec = importlib.util.spec_from_file_location(name, TOOLS / (name + '.py'))
  assert spec is not None and spec.loader is not None
  result = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(result)
  return result


@pytest.mark.skipif(os.environ.get('ARABESQUE_X11_TEST') != '1', reason='Needs an explicitly disposable Xvfb and XCB extensions')
def test_reference_damage_shm_and_input():
  x11, runtime = module('browser_x11'), module('browser_session')
  x = x11.X11('unix/' + os.environ['DISPLAY'])
  fds, buffers = [], []
  try:
    assert C.sizeof(x11.Screen) == 40
    for _ in range(2):
      fd = runtime.sealed_slot(x.size)
      fds.append(fd)
      buffers.append(mmap.mmap(fd, x.size))
    x.reference(buffers)
    segments = [x.attach(fd) for fd in fds]
    # Repeated reuse catches FD ownership, request/reply and stride mistakes.
    for _ in range(50):
      x.finish(x.wait(x.capture(segments[1])), buffers[1], True)
      assert buffers[0][:] == buffers[1][:]
    for text in ('a', 'A', '€', '•', 'é', '😀'):
      code = ord(text)
      x.key(code if code <= 255 else 0x01000000 | code)
    x.motion(20, 20)
    x.button(1, True)
    x.button(1, False)
    x.sync()
    x.damage_subtract(x.connection, x.damage_id, 0, 0)
    x.sync()
    x.reference(buffers)
    assert x.damaged()
  finally:
    x.close()
    for buffer in buffers:
      buffer.close()
    for fd in fds:
      os.close(fd)
