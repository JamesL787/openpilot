"""On-demand Firefox owner and isolated worker. The worker uses only the standard library."""

import array
import ctypes as C
import fcntl
import importlib.util
import json
import mmap
import os
from pathlib import Path
import select
import signal
import socket
import stat
import struct
import subprocess
import sys
from threading import Event, Thread
import time
import uuid

ROOT = Path('/data/arabesque-firefox')
RUNTIME = ROOT / 'runtime'
STATE = ROOT / 'state'
BROWSER_UID = 61234
# Linux UAPI constants also work with Python builds made against pre-memfd libc headers.
ADD_SEALS, GET_SEALS, SEALS = 1033, 1034, 7
LEASE_SECONDS = 2.0
MAX_PACKET = 4096


def packet(sock, message, fds=()):
  data = json.dumps(message, separators=(',', ':'), ensure_ascii=True).encode('ascii')
  if len(data) > MAX_PACKET:
    raise ValueError('Browser control packet too large')
  rights = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', fds))] if fds else []
  if sock.sendmsg([data], rights) != len(data):
    raise RuntimeError('Incomplete browser packet')


def receive(sock, fd_count=0):
  data, ancillary, flags, _ = sock.recvmsg(MAX_PACKET, socket.CMSG_SPACE(8 * array.array('i').itemsize), socket.MSG_CMSG_CLOEXEC)
  fds = []
  try:
    for level, kind, payload in ancillary:
      if (level, kind) != (socket.SOL_SOCKET, socket.SCM_RIGHTS):
        raise ValueError('Unexpected browser ancillary data')
      values = array.array('i')
      values.frombytes(payload)
      fds.extend(values)
    if not data:
      raise EOFError('Browser connection closed')
    if flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC) or len(fds) != fd_count:
      raise ValueError('Truncated browser packet or unexpected descriptors')
    message = json.loads(data)
    if not isinstance(message, dict) or not isinstance(message.get('type'), str):
      raise ValueError('Invalid browser control message')
    return message, fds
  except BaseException:
    for fd in fds:
      os.close(fd)
    raise


def credentials(sock):
  return struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))


def geometry(width, height, fps):
  if type(width) is not int or type(height) is not int or not 320 <= width <= 1600 or not 240 <= height <= 1200:
    raise ValueError('Invalid browser geometry')
  if type(fps) is not int or not 1 <= fps <= 30:
    raise ValueError('Invalid browser frame rate')
  return width * height * 4


def sealed_slot(size):
  libc = C.CDLL(None, use_errno=True)
  try:
    create = libc.memfd_create
  except AttributeError:
    raise RuntimeError('memfd_create is unavailable') from None
  create.argtypes, create.restype = [C.c_char_p, C.c_uint], C.c_int
  fd = create(b'arabesque-frame', 3)  # MFD_CLOEXEC | MFD_ALLOW_SEALING
  if fd < 0:
    raise OSError(C.get_errno(), 'memfd_create failed')
  try:
    os.ftruncate(fd, size)
    fcntl.fcntl(fd, ADD_SEALS, SEALS)
    if fcntl.fcntl(fd, GET_SEALS) != SEALS:
      raise RuntimeError('Cannot seal browser frame size')
    return fd
  except BaseException:
    os.close(fd)
    raise


def launch_command(unit, address, width, height, fps, capture):
  bridge = Path(__file__).resolve().parent
  # Mask user/vehicle data, then expose only the immutable runtime, Python and the browser's own state.
  binds = {str(RUNTIME), str(Path(sys.prefix).resolve()), str(Path(sys.base_prefix).resolve())}
  empty, devices = RUNTIME / 'isolation/empty', RUNTIME / 'isolation/devices'
  properties = [
    'Type=notify', 'NotifyAccess=main', 'TimeoutStartSec=12', 'WatchdogSec=4', 'WatchdogSignal=SIGTERM', 'TimeoutAbortSec=3',
    'KillMode=mixed', 'TimeoutStopSec=3', 'SendSIGKILL=yes', 'Restart=no', 'LimitCORE=0',
    'NoNewPrivileges=yes', 'CapabilityBoundingSet=CAP_SETUID CAP_SETGID',
    'ProtectSystem=strict', 'PrivateTmp=yes',
    'ProtectControlGroups=yes', 'UMask=0077',
    # ProtectKernelTunables also installs seccomp; retain its mount restrictions without hiding Firefox's filter.
    'InaccessiblePaths=-/proc/kallsyms -/proc/kcore',
    'TemporaryFileSystem=/data:ro /persist:ro /mnt:ro /media:ro /cache:ro /rwtmp:ro /var:ro /dev/shm:rw,nosuid,nodev,noexec,mode=1777',
    'BindReadOnlyPaths=' + ' '.join(sorted(binds)) + f' {bridge}:/tmp/arabesque-bridge '
    + f'{empty}:/home {empty}:/root {empty}:/run/user {devices}:/dev '
    + '/sys /proc/sys -/proc/acpi -/proc/apm -/proc/asound -/proc/bus -/proc/fs -/proc/irq '
    + '-/proc/latency_stats -/proc/mtrr -/proc/scsi -/proc/sysrq-trigger -/proc/timer_stats',
    f'BindPaths={STATE} /dev/null /dev/zero /dev/random /dev/urandom', f'ReadWritePaths={STATE}', 'WorkingDirectory=/tmp',
    # This kernel has no CFS bandwidth or pids controller; use fair shares and the per-UID process limit.
    'CPUAffinity=0-5', 'CPUSchedulingPolicy=other', 'Nice=10', 'CPUWeight=10', 'MemoryMax=1G', 'LimitNPROC=1024',
    'StandardOutput=null', 'StandardError=journal',
  ]
  python = str(Path(sys.executable).absolute())
  # Use the real interpreter; a venv symlink may point through the masked /home tree.
  python = str(Path(python).resolve())
  command = ['sudo', '-n', '/usr/bin/timeout', '--kill-after=1', '15', '/usr/bin/systemd-run', '--quiet', '--collect', f'--unit={unit}']
  command += [f'--property={value}' for value in properties]
  command += ['/usr/bin/setpriv', f'--reuid={BROWSER_UID}', f'--regid={BROWSER_UID}', '--clear-groups', '--no-new-privs',
              python, '-I', '-u', '-c',
              "import sys; sys.path.insert(0, '/tmp/arabesque-bridge'); from browser_session import worker_main; worker_main()",
              address, str(os.getuid()), str(os.getpid()), os.readlink('/proc/self/ns/mnt'),
              str(width), str(height), str(fps), capture]
  return command


def preparation_command(unit, address):
  bridge = Path(__file__).resolve().parent
  properties = [
    'Type=notify', 'NotifyAccess=main', 'TimeoutStartSec=12', 'WatchdogSec=4', 'WatchdogSignal=SIGTERM',
    'TimeoutAbortSec=3', 'KillMode=mixed', 'TimeoutStopSec=3', 'Restart=no', 'RuntimeMaxSec=900', 'LimitCORE=0',
    # /data is owned by comma; only this mkdir runs outside the preparer's capability bound.
    f'ExecStartPre=-+/usr/bin/mkdir -m 0755 {ROOT}',
    'NoNewPrivileges=yes', 'CapabilityBoundingSet=CAP_CHOWN', 'ProtectSystem=strict', 'ReadWritePaths=/data',
    'PrivateTmp=yes', 'ProtectKernelTunables=yes', 'ProtectControlGroups=yes', 'UMask=0022', 'WorkingDirectory=/tmp',
    'CPUAffinity=0-5', 'CPUSchedulingPolicy=other', 'Nice=10', 'MemoryMax=1G', 'StandardOutput=null', 'StandardError=journal',
  ]
  command = ['sudo', '-n', '/usr/bin/timeout', '--kill-after=1', '15', '/usr/bin/systemd-run', '--quiet', '--collect', f'--unit={unit}']
  command += [f'--property={value}' for value in properties]
  command += [str(Path(sys.executable).resolve()), '-I', '-u', '-c',
              f'import sys; sys.path.insert(0, {str(bridge)!r}); from browser_session import preparation_main; preparation_main()',
              address, str(os.getuid()), str(os.getpid())]
  return command


class BrowserSession:
  pending_stop = None

  def __init__(self, width, height, fps, capture='auto'):
    self.width, self.height, self.fps = width, height, fps
    self.size = geometry(width, height, fps)
    if capture not in ('auto', 'reference', 'shm'):
      raise ValueError('Invalid capture mode')
    self._capture = capture
    self.error, self.status = '', 'Checking isolated Firefox runtime…'
    self.ready = False
    self._listener = self._socket = self._launcher = None
    self._fds, self.buffers, self._frames = [], [], []
    self._unit = ''
    self._started = self._heartbeat = time.monotonic()
    self._preparing = self._next_start = False
    self.stopped = Event()
    self.stopped.set()
    self._start()

  def _start(self):
    try:
      if ROOT.is_symlink() or RUNTIME.is_symlink():
        raise RuntimeError('Firefox runtime path must not be a symlink')
      self._preparing = not RUNTIME.exists()
      paths = (ROOT, RUNTIME, STATE, RUNTIME / 'firefox/firefox')
      if self._preparing:
        paths = (ROOT,) if ROOT.exists() else ()
      for path in paths:
        info = path.stat()
        if info.st_uid != (BROWSER_UID if path == STATE else 0) or info.st_mode & 0o022:
          raise RuntimeError('Firefox runtime has unsafe ownership or permissions')
      if not self._preparing and not (RUNTIME / 'ready.json').is_file():
        raise RuntimeError('Firefox runtime is not prepared')
      self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
      address = 'arabesque-firefox-' + uuid.uuid4().hex
      self._listener.bind('\0' + address)
      self._listener.listen(1)
      self._listener.setblocking(False)
      if not self._preparing:
        for _ in range(2):
          fd = sealed_slot(self.size)
          self._fds.append(fd)
          self.buffers.append(mmap.mmap(fd, self.size, access=mmap.ACCESS_READ))
      self._unit = 'arabesque-firefox-' + uuid.uuid4().hex
      self.stopped = Event()
      self._started = self._heartbeat = time.monotonic()
      self.status = 'Preparing Firefox for first use…' if self._preparing else 'Starting Firefox…'
      command = (preparation_command(self._unit, address) if self._preparing else
                 launch_command(self._unit, address, self.width, self.height, self.fps, self._capture))
      self._launcher = subprocess.Popen(command,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, ValueError, RuntimeError) as e:
      self.error = f'{e}. Close Firefox and reopen it to retry.'
      self.close()

  def send(self, message):
    if self._socket is not None:
      try:
        packet(self._socket, message)
        return True
      except (OSError, ValueError, RuntimeError) as e:
        self.fail(str(e))
    return False

  def fail(self, error):
    self.error = error
    self.close()

  def poll(self):
    if self._next_start:
      if not self.stopped.is_set():
        return
      self._next_start = False
      self._start()
    if not self._unit:
      return
    try:
      now = time.monotonic()
      if self._socket is None:
        try:
          peer, _ = self._listener.accept()
        except BlockingIOError:
          if now - self._started > 12 or self._launcher.poll() not in (None, 0):
            raise RuntimeError('Isolated Firefox could not start; check the transient unit journal') from None
          return
        if credentials(peer)[1] != (0 if self._preparing else BROWSER_UID):
          peer.close()
          raise RuntimeError('Unexpected Firefox worker identity')
        self._socket = peer
        peer.setblocking(False)
        if self._preparing:
          packet(peer, {'type': 'prepare'})
        else:
          packet(peer, {'type': 'init', 'width': self.width, 'height': self.height, 'fps': self.fps}, self._fds)
        self._listener.close()
        self._listener = None
      if not self._preparing and not self.ready and now - self._started > 45:
        raise TimeoutError('Firefox startup checks timed out')
      if now - self._heartbeat >= 0.25:
        if not self.send({'type': 'lease'}):
          return
        self._heartbeat = now
      for _ in range(8):
        try:
          message, _ = receive(self._socket)
        except BlockingIOError:
          break
        if self._preparing and message['type'] == 'status' and set(message) == {'type', 'message'} and isinstance(message['message'], str):
          self.status = message['message'][:512]
        elif self._preparing and message == {'type': 'prepared'}:
          self.close()
          self._next_start = True
          self.status = 'Starting Firefox…'
          return
        elif not self._preparing and message['type'] == 'ready' and set(message) == {'type', 'capture'} and message['capture'] in ('shm', 'reference'):
          self.ready = True
          self.status = 'MIT-SHM FD' if message['capture'] == 'shm' else 'GetImage reference capture'
        elif message['type'] == 'frame' and set(message) == {'type', 'slot'} and type(message['slot']) is int:
          slot = message['slot']
          if not self.ready or slot not in (0, 1) or slot in self._frames:
            raise ValueError('Invalid Firefox frame lease')
          self._frames.append(slot)
        elif message['type'] == 'error' and set(message) == {'type', 'message'} and isinstance(message['message'], str):
          raise RuntimeError(message['message'][:512])
        else:
          raise ValueError('Unexpected Firefox worker response')
    except (OSError, ValueError, RuntimeError, EOFError) as e:
      self.fail(str(e))

  def take_frame(self):
    if not self._frames:
      return None
    frames, self._frames = self._frames, []
    for slot in frames[:-1]:
      self.release(slot)
    return (frames[-1], self.buffers[frames[-1]]) if self.ready else None

  def release(self, slot):
    self.send({'type': 'release', 'slot': slot})

  def reset_input(self):
    self.send({'type': 'reset'})

  def close(self):
    self._next_start = False
    if self._socket is not None:
      try:
        packet(self._socket, {'type': 'close'})
      except OSError:
        pass
      self._socket.close()
      self._socket = None
    if self._listener is not None:
      self._listener.close()
      self._listener = None
    if self._unit:
      # Reap both commands away from the UI thread; PID 1 stops every grandchild before allowing a resume.
      BrowserSession.pending_stop = self.stopped
      Thread(target=stop_unit, args=(self._unit, self._launcher, self.stopped), daemon=True, name='firefox-stop').start()
      self._unit = ''
    if self._launcher is not None:
      self._launcher.poll()
    self.ready = False
    self._frames = []
    for buffer in self.buffers:
      buffer.close()
    self.buffers = []
    for fd in self._fds:
      os.close(fd)
    self._fds = []


def stop_unit(unit, launcher, stopped):
  try:
    subprocess.run(['sudo', '-n', '/usr/bin/timeout', '--kill-after=1', '4', '/usr/bin/systemctl', 'stop', unit],
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6, check=False)
  except (OSError, subprocess.TimeoutExpired):
    pass  # EOF, the owner lease and PID 1's watchdog remain independent cleanup paths.
  finally:
    try:
      if launcher is not None:
        launcher.wait(timeout=12)
    except (OSError, subprocess.TimeoutExpired):
      pass
    finally:
      stopped.set()


def status(pid):
  return dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)


def no_new_privileges():
  libc = C.CDLL(None, use_errno=True)
  libc.prctl.argtypes = [C.c_int, C.c_ulong, C.c_ulong, C.c_ulong, C.c_ulong]
  libc.prctl.restype = C.c_int
  result = libc.prctl(39, 0, 0, 0, 0)  # PR_GET_NO_NEW_PRIVS; /proc omits this field on AGNOS's kernel.
  if result not in (0, 1):
    raise OSError(C.get_errno(), 'Cannot query no-new-privileges')
  return result


def check_isolation(host_mount):
  current = status('self')
  if (os.getresuid() != (BROWSER_UID,) * 3 or os.getresgid() != (BROWSER_UID,) * 3 or os.getgroups() or
      any(int(current.get(key, '0').strip(), 16) for key in ('CapEff', 'CapPrm', 'CapInh', 'CapAmb')) or
      no_new_privileges() != 1):
    raise RuntimeError('Firefox worker privilege drop failed')
  # Do not install systemd syscall filters: on kernel 4.9 that would hide whether Firefox itself enabled seccomp.
  if current.get('Seccomp', '').strip() != '0':
    raise RuntimeError('Cannot independently verify Firefox seccomp with an inherited filter')
  if os.readlink('/proc/self/ns/mnt') == host_mount:
    raise RuntimeError('Firefox filesystem isolation is missing')
  if any(Path(path).exists() for path in ('/data/params', '/persist/comma', str(ROOT / '.isolation-probe'))):
    raise RuntimeError('Firefox can see host vehicle data')
  mounts = {fields[4]: (fields[5], fields[fields.index('-') + 1]) for line in Path('/proc/self/mountinfo').read_text().splitlines()
            if (fields := line.split())}
  for path in ('/data', '/persist', '/mnt', '/media', '/cache', '/rwtmp', '/var'):
    if path not in mounts or mounts[path][1] != 'tmpfs' or 'ro' not in mounts[path][0].split(','):
      raise RuntimeError(f'Firefox host-data mask missing: {path}')
  for path in ('/home', '/root', '/run/user'):
    if (not os.path.samefile(path, RUNTIME / 'isolation/empty') or os.listdir(path) or
        not os.statvfs(path).f_flag & os.ST_RDONLY):
      raise RuntimeError(f'Firefox home mask missing: {path}')
  if (not os.path.samefile('/dev', RUNTIME / 'isolation/devices') or
      set(os.listdir('/dev')) != {'null', 'zero', 'random', 'urandom', 'shm'} or mounts.get('/dev/shm', ('', ''))[1] != 'tmpfs'):
    raise RuntimeError('Firefox private device tree is missing')
  for name, minor in (('null', 3), ('zero', 5), ('random', 8), ('urandom', 9)):
    device = os.stat('/dev/' + name)
    if not stat.S_ISCHR(device.st_mode) or device.st_rdev != os.makedev(1, minor):
      raise RuntimeError(f'Firefox device binding is invalid: {name}')
  if 6 in os.sched_getaffinity(0) or os.sched_getscheduler(0) != os.SCHED_OTHER:
    raise RuntimeError('Firefox inherited display scheduling')
  for path in ('/sys', '/proc/sys', '/proc/bus', '/proc/fs', '/proc/irq'):
    if not os.statvfs(path).f_flag & os.ST_RDONLY:
      raise RuntimeError(f'Firefox kernel interface is writable: {path}')
  if not os.statvfs(RUNTIME).f_flag & os.ST_RDONLY:
    raise RuntimeError('Firefox application is writable')
  probe = STATE / '.write-probe'
  probe.write_text('ok')
  probe.unlink()


def enough_space():
  disk = os.statvfs(STATE)
  return disk.f_bavail * disk.f_frsize >= max(5 * 1024**3, disk.f_blocks * disk.f_frsize // 10)


def content_sandboxed(parent):
  """Require a Firefox browser-content child, rather than a GPU/utility helper, with active seccomp."""
  # AGNOS disables CONFIG_CHECKPOINT_RESTORE, so /proc/task/*/children does not exist.
  groups = Path(f'/proc/{parent}/cgroup').read_text().splitlines()
  group = next((line[3:] for line in groups if line.startswith('0::')), None)
  if group is None:
    raise RuntimeError('Firefox process verification requires its unified cgroup')
  members = (Path('/sys/fs/cgroup') / group.lstrip('/') / 'cgroup.procs').read_text().split()
  inherited_nnp = no_new_privileges() == 1
  for pid in members:
    try:
      # Firefox rewrites its process title into one space-separated argv entry after fork.
      args = Path(f'/proc/{pid}/cmdline').read_bytes().replace(b'\0', b' ').split()
      info = status(pid)
      if b'-parentPid' not in args or args[args.index(b'-parentPid') + 1:][:1] != [str(parent).encode()]:
        continue
      # This worker launches Firefox directly; no-new-privileges is inherited and cannot be unset by descendants.
      child_nnp = info['NoNewPrivs'].strip() == '1' if 'NoNewPrivs' in info else inherited_nnp
      if (b'-contentproc' in args and b'-isForBrowser' in args and args[-1] == b'tab' and
          info.get('Seccomp', '').strip() == '2' and
          child_nnp and info.get('Uid', '').split()[:1] == [str(os.getuid())] and not int(info['CapEff'].strip(), 16)):
        return True
    except (OSError, ValueError):
      continue
  return False


def stop_process(process):
  if process is not None and process.poll() is None:
    process.terminate()
    try:
      process.wait(timeout=1)
    except subprocess.TimeoutExpired:
      process.kill()
      process.wait(timeout=1)


def stop_firefox(process, x):
  if x is not None and process is not None and process.poll() is None:
    try:
      x.key(ord('q'), ctrl=True)
      x.flush(x.connection)
      deadline = time.monotonic() + 1.5
      while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    except (OSError, RuntimeError, ValueError):
      pass  # PID 1 still bounds shutdown if Firefox is hung or a dialog prevents quitting.
  stop_process(process)


def notify(message):
  address = os.environ.get('NOTIFY_SOCKET', '')
  if not address:
    raise RuntimeError('Firefox transient supervisor is missing')
  with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC) as sock:
    sock.settimeout(0.1)
    sock.sendto(message.encode('ascii'), '\0' + address[1:] if address.startswith('@') else address)


def preparation_main():
  address, owner_uid, owner_pid = sys.argv[1:]
  cancel, finished = Event(), Event()
  progress: dict[str, str] = {'status': 'Preparing Firefox for first use…'}
  thread = None
  sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
  sock.settimeout(5)
  signal.signal(signal.SIGTERM, lambda *_: cancel.set())
  signal.signal(signal.SIGINT, lambda *_: cancel.set())

  def report(message):
    if cancel.is_set():
      raise InterruptedError('Firefox preparation cancelled')
    progress['status'] = message[:512]

  def prepare():
    try:
      path = Path(__file__).resolve().parents[5] / 'tools/arabesque_firefox/setup.py'
      spec = importlib.util.spec_from_file_location('firefox_setup', path)
      if spec is None or spec.loader is None:
        raise RuntimeError('Firefox preparation is unavailable')
      setup = importlib.util.module_from_spec(spec)
      spec.loader.exec_module(setup)
      setup.ROOT, setup.report = ROOT, report
      setup.prepare()
    except Exception as e:
      progress['error'] = str(e)[:512]
    finally:
      finished.set()

  try:
    sock.connect('\0' + address)
    if credentials(sock)[:2] != (int(owner_pid), int(owner_uid)):
      raise RuntimeError('Firefox preparation owner identity mismatch')
    message, _ = receive(sock)
    if message != {'type': 'prepare'}:
      raise ValueError('Invalid Firefox preparation handshake')
    sock.setblocking(False)
    notify('READY=1\nWATCHDOG=1')
    thread = Thread(target=prepare, daemon=True, name='firefox-prepare')
    thread.start()
    last_lease = last_watchdog = time.monotonic()
    status_sent = ''
    while not cancel.is_set():
      now = time.monotonic()
      if now - last_lease > LEASE_SECONDS:
        raise TimeoutError('Firefox preparation owner stopped responding')
      if now - last_watchdog >= 1:
        notify('WATCHDOG=1')
        last_watchdog = now
      for _ in range(32):
        try:
          message, _ = receive(sock)
        except BlockingIOError:
          break
        if message == {'type': 'lease'}:
          last_lease = now
        elif message == {'type': 'close'}:
          cancel.set()
          break
        else:
          raise ValueError('Invalid Firefox preparation command')
      if cancel.is_set():
        break
      if finished.is_set():
        if failure := progress.get('error'):
          raise RuntimeError(failure)
        packet(sock, {'type': 'prepared'})
        break
      status = progress['status']
      if status != status_sent:
        packet(sock, {'type': 'status', 'message': status})
        status_sent = status
      select.select([sock], [], [], 0.1)
  except (OSError, ValueError, RuntimeError, EOFError) as e:
    print(f'Firefox preparation: {str(e)[:512]}', file=sys.stderr, flush=True)
    try:
      packet(sock, {'type': 'error', 'message': str(e)[:512]})
    except OSError:
      pass
  finally:
    cancel.set()
    if thread is not None:
      thread.join(timeout=1)
    sock.close()


def worker_main():
  # This is the first Python code executed after systemd's mount sandbox and setpriv.
  from browser_x11 import X11
  address, owner_uid, owner_pid, host_mount, width, height, fps, mode = sys.argv[1:]
  width, height, fps = int(width), int(height), int(fps)
  size = geometry(width, height, fps)
  sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET | socket.SOCK_CLOEXEC)
  sock.settimeout(5)
  xvfb = firefox = x = None
  buffers, fds = [], []
  stopping = False

  def terminate(*_):
    nonlocal stopping
    stopping = True

  signal.signal(signal.SIGTERM, terminate)
  signal.signal(signal.SIGINT, terminate)
  try:
    sock.connect('\0' + address)
    if credentials(sock)[:2] != (int(owner_pid), int(owner_uid)):
      raise RuntimeError('Firefox owner identity mismatch')
    message, fds = receive(sock, 2)
    if message != {'type': 'init', 'width': width, 'height': height, 'fps': fps}:
      raise ValueError('Firefox geometry handshake failed')
    check_isolation(host_mount)
    if not enough_space():
      raise RuntimeError('Insufficient free storage for Firefox')
    for fd in fds:
      info = os.fstat(fd)
      if not stat.S_ISREG(info.st_mode) or info.st_size != size or fcntl.fcntl(fd, GET_SEALS) != SEALS:
        raise ValueError('Invalid Firefox shared frame descriptor')
      buffers.append(mmap.mmap(fd, size, access=mmap.ACCESS_WRITE))
    notify('READY=1\nWATCHDOG=1')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(STATE), 'TMPDIR': '/tmp', 'LANG': 'C.UTF-8',
           'LD_LIBRARY_PATH': str(RUNTIME / 'usr/lib/aarch64-linux-gnu'),
           'XDG_DATA_DIRS': f'{RUNTIME}/usr/share:/usr/share', 'XDG_CACHE_HOME': str(STATE / 'cache'),
           'GSETTINGS_SCHEMA_DIR': str(RUNTIME / 'usr/share/glib-2.0/schemas'), 'GSETTINGS_BACKEND': 'memory',
           'GDK_BACKEND': 'x11', 'MOZ_ENABLE_WAYLAND': '0', 'MOZ_CRASHREPORTER_DISABLE': '1',
           # Off-road teardown may interrupt startup; keep recovery under our bounded supervisor.
           'MOZ_DISABLE_AUTO_SAFE_MODE': '1',
           'LIBGL_ALWAYS_SOFTWARE': '1', 'NO_AT_BRIDGE': '1'}
    auth = Path('/tmp/firefox.xauth')
    auth.touch(mode=0o600)
    cookie = os.urandom(16).hex()
    # PrivateTmp makes this fixed display name private to this one transient service.
    display = ':77'
    subprocess.run(['/usr/bin/xauth', '-f', str(auth), 'add', display, '.', cookie], env=env, check=True, timeout=2,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env.update(DISPLAY=display, XAUTHORITY=str(auth))
    os.environ['XAUTHORITY'] = str(auth)
    xvfb = subprocess.Popen(['/usr/bin/Xvfb', display, '-screen', '0', f'{width}x{height}x24', '-nolisten', 'tcp',
                             '-nolisten', 'local', '-auth', str(auth), '-noreset', '-extension', 'GLX'], env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    # -nolisten local disables the shared abstract socket; the filesystem socket stays in PrivateTmp.
    for _ in range(100):
      if stopping or xvfb.poll() is not None:
        raise RuntimeError('Private Xvfb failed to start')
      if Path('/tmp/.X11-unix/X77').is_socket():
        x = X11('unix/:77', RUNTIME / 'usr/lib/aarch64-linux-gnu')
        break
      time.sleep(0.02)
    if x is None or (x.width, x.height) != (width, height):
      raise RuntimeError('Private Xvfb geometry check failed')
    x.reference(buffers)
    notify('WATCHDOG=1')
    segments = []
    if mode != 'reference':
      try:
        segments = [x.attach(fd) for fd in fds]
        x.finish(x.wait(x.capture(segments[1])), buffers[1], True)
        compare = C.CDLL(None).memcmp
        compare.argtypes, compare.restype = [C.c_void_p, C.c_void_p, C.c_size_t], C.c_int
        if compare(C.addressof(C.c_char.from_buffer(buffers[0])), C.addressof(C.c_char.from_buffer(buffers[1])), size):
          raise RuntimeError('MIT-SHM frame differs from reference GetImage')
      except (OSError, RuntimeError, TimeoutError):
        if mode == 'shm':
          raise
        segments = []
    x.clear_reference()
    profile = STATE / 'profile'
    profile.mkdir(mode=0o700, exist_ok=True)
    first_run = not (profile / 'prefs.js').exists()
    preferences = {'browser.shell.checkDefaultBrowser': False, 'browser.startup.homepage_override.mstone': 'ignore',
                   'browser.warnOnQuitShortcut': False,
                   'browser.startup.page': 3,
                   'browser.cache.disk.capacity': 65536, 'browser.cache.disk.smart_size.enabled': False,
                   'browser.download.dir': str(STATE / 'downloads'), 'browser.download.folderList': 2,
                   'gfx.webrender.software': True, 'layers.acceleration.disabled': True,
                   'media.hardware-video-decoding.enabled': False, 'dom.ipc.processCount': 2}
    (STATE / 'downloads').mkdir(mode=0o700, exist_ok=True)
    (profile / 'user.js').write_text('\n'.join(f'user_pref({json.dumps(key)}, {json.dumps(value)});' for key, value in preferences.items()))
    page = Path('/tmp/firefox-start.html')
    page.write_text('''<!doctype html><meta charset="utf-8"><title>Arabesque</title>
<style>body{background:#191327;color:white;font:24px sans-serif;padding:32px}input{font:24px sans-serif}</style>
<h1>Firefox in Arabesque</h1><p>Use the Firefox address bar to browse.</p>
<p>Scroll mode moves pages; Pointer mode drags and selects. Touch Keyboard to type.</p>
<p>Desktop closes Firefox completely.</p><input placeholder="Test typing here">''')
    command = [str(RUNTIME / 'firefox/firefox'), '--no-remote', '--new-instance', '--profile', str(profile),
               '--width', str(width), '--height', str(height)]
    firefox = subprocess.Popen(command + ([page.as_uri()] if first_run else []), env=env,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    sock.setblocking(False)
    free, leased, pending = [0, 1], set(), None
    dirty, ready = True, False
    started = last_lease = last_capture = last_disk = last_watchdog = time.monotonic()
    down = set()
    while not stopping:
      now = time.monotonic()
      if now - last_lease > LEASE_SECONDS:
        raise TimeoutError('Firefox owner stopped responding')
      if now - last_watchdog >= 1:
        notify('WATCHDOG=1')
        last_watchdog = now
      if xvfb.poll() is not None or firefox.poll() is not None:
        raise RuntimeError(f'Firefox or Xvfb exited (Firefox={firefox.poll()}, Xvfb={xvfb.poll()})')
      if now - last_disk >= 5:
        last_disk = now
        if not enough_space():
          raise RuntimeError('Firefox stopped to preserve free storage')
      for _ in range(32):
        try:
          message, _ = receive(sock)
        except BlockingIOError:
          break
        kind = message['type']
        if kind == 'lease' and set(message) == {'type'}:
          last_lease = now
        elif kind == 'release' and set(message) == {'type', 'slot'} and type(message['slot']) is int and message['slot'] in leased:
          slot = message['slot']
          leased.remove(slot)
          free.append(slot)
        elif kind in ('close', 'reset') and set(message) == {'type'}:
          for button in down:
            x.button(button, False)
          down.clear()
          stopping |= kind == 'close'
        elif kind == 'input' and ready:
          inject(x, message, down, width, height)
        else:
          raise ValueError('Invalid Firefox owner command')
      dirty |= x.damaged()
      if not ready and now - last_capture >= 0.25:
        last_capture = now
        if content_sandboxed(firefox.pid) and x.focus_browser():
          ready = True
          packet(sock, {'type': 'ready', 'capture': 'shm' if segments else 'reference'})
        elif now - started > 30:
          raise RuntimeError('Firefox content sandbox could not be verified')
      if pending:
        slot, request, deadline = pending
        if reply := x.poll(request):
          x.finish(reply, buffers[slot], bool(segments))
          packet(sock, {'type': 'frame', 'slot': slot})
          leased.add(slot)
          pending = None
        elif now >= deadline:
          raise TimeoutError('Firefox capture stalled')
      if ready and dirty and free and pending is None and now - last_capture >= 1 / fps:
        slot = free.pop()
        pending = slot, x.capture(segments[slot] if segments else 0), now + 2
        dirty, last_capture = False, now
      x.flush(x.connection)
      select.select([sock, x.fd], [], [], min(0.02, 1 / fps) if pending or dirty or not ready else 0.25)
  except (OSError, ValueError, RuntimeError, EOFError, subprocess.SubprocessError) as e:
    print(f'Firefox bridge: {str(e)[:512]}', file=sys.stderr, flush=True)
    try:
      packet(sock, {'type': 'error', 'message': str(e)[:512]})
    except OSError:
      pass
  finally:
    stop_firefox(firefox, x)
    if x is not None:
      x.close()
    stop_process(xvfb)
    for buffer in buffers:
      buffer.close()
    for fd in fds:
      os.close(fd)
    sock.close()


def inject(x, message, down, width, height):
  if set(message) != {'type', 'event', 'a', 'b'} or not isinstance(message['event'], str):
    raise ValueError('Invalid Firefox input packet')
  event, a, b = message['event'], message['a'], message['b']
  if event == 'motion' and type(a) is int and type(b) is int and 0 <= a < width and 0 <= b < height:
    x.motion(a, b)
  elif event == 'button' and type(a) is int and a in (1, 3, 4, 5) and type(b) is bool:
    if b:
      down.add(a)
    else:
      down.discard(a)
    x.button(a, b)
  elif event == 'key' and type(a) is int and 0 < a <= 0x0110ffff and type(b) is int and 0 <= b <= 7:
    x.key(a, ctrl=bool(b & 1), alt=bool(b & 2), shift=bool(b & 4))
  else:
    raise ValueError('Invalid Firefox input bounds')


if __name__ == '__main__':
  import argparse
  parser = argparse.ArgumentParser(description='Run isolated Firefox and reference/SHM checks without starting the UI.')
  parser.add_argument('--capture', choices=('reference', 'shm'), default='reference')
  parser.add_argument('--seconds', type=int, default=45)
  args = parser.parse_args()
  # The diagnostic entry must not bypass the UI's fresh off-road authority gate.
  sys.path.insert(0, str(Path(__file__).resolve().parents[6]))
  from openpilot.common.params import Params
  from openpilot.starpilot.galaxy.settings import LiveContextSource
  authority = LiveContextSource(Params(), evidence_wait_ms=1500)
  session = None
  try:
    if not authority.offroad():
      raise SystemExit('Firefox checks require fresh off-road authority')
    authority.evidence_wait_ms = 0
    session = BrowserSession(1440, 650, 20, args.capture)
    deadline, frames = time.monotonic() + max(1, min(args.seconds, 120)), 0
    while not session.error and time.monotonic() < deadline:
      if not authority.offroad():
        raise SystemExit('Firefox check stopped: off-road authority lost')
      session.poll()
      if frame := session.take_frame():
        slot, _ = frame
        session.release(slot)
        frames += 1
      time.sleep(0.01)
    if session.error or not frames:
      raise SystemExit(session.error or 'No Firefox frame received')
    print(json.dumps({'capture': session.status, 'frames': frames, 'runtime': 'isolated', 'content_seccomp': True}))
  finally:
    if session is not None:
      session.close()
    authority.close()
