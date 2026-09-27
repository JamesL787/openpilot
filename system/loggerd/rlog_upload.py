# StarPilot: which rlogs UploadRlogs sends, shared by the uploader and the hardwared shutdown hold.
#
# The first drive seen with the toggle on is the anchor, stored as an xattr on the log root. Every rlog from the
# anchor route onward goes up oldest first, so an unfinished previous drive completes before the one in progress.
# Routes older than the anchor (the backlog from before the toggle was on) are never sent. Turning the toggle off
# clears the anchor, so turning it back on starts again at the drive in progress.
#
# Kept free of uploader imports (Api, cereal) so hardwared can use it without an import cycle. Upload marks are
# read uncached here because the uploader sets them from another process.
import errno
import os

from openpilot.system.loggerd.xattr_cache import _backend_getxattr

ANCHOR_ATTR_NAME = "user.rlog_upload_from"
UPLOAD_ATTR_NAME = "user.upload"
UPLOAD_ATTR_VALUE = b"1"
RLOG_NAMES = ("rlog", "rlog.zst")


def route_of(logdir: str) -> str | None:
  route, sep, seg = logdir.rpartition("--")
  return route if sep and seg.isdigit() else None


def route_sort_key(route: str) -> tuple[str, str]:
  # same order as uploader.get_directory_sort: the old date-named format sorts first
  return ("0" if route.startswith("2024-") else "1", route)


def segment_dirs(root: str) -> list[str]:
  try:
    dirs = [d for d in os.listdir(root) if route_of(d) is not None and os.path.isdir(os.path.join(root, d))]
  except OSError:
    return []
  return sorted(dirs, key=lambda d: (route_sort_key(route_of(d)), int(d.rpartition("--")[2])))


def current_route(root: str) -> str | None:
  dirs = segment_dirs(root)
  return route_of(dirs[-1]) if dirs else None


def _read_xattr(path: str, attr_name: str) -> bytes | None:
  try:
    return _backend_getxattr(path, attr_name)
  except OSError as e:
    if e.errno in (errno.ENOENT, errno.ENODATA, getattr(errno, "ENOATTR", errno.ENODATA)):
      return None
    raise


def get_anchor(root: str) -> str | None:
  try:
    value = _read_xattr(root, ANCHOR_ATTR_NAME)
  except OSError:
    return None
  return value.decode() if value else None


def ensure_anchor(root: str) -> str | None:
  anchor = get_anchor(root)
  if anchor is None:
    anchor = current_route(root)
    if anchor is not None:
      try:
        os.setxattr(root, ANCHOR_ATTR_NAME, anchor.encode())
      except OSError:
        pass  # no xattr support: fall back to the drive in progress each time
  return anchor


def clear_anchor(root: str) -> None:
  try:
    os.removexattr(root, ANCHOR_ATTR_NAME)
  except OSError:
    pass


def in_upload_window(logdir: str, anchor: str | None) -> bool:
  route = route_of(logdir)
  return route is not None and anchor is not None and route_sort_key(route) >= route_sort_key(anchor)


def rlogs_pending(root: str) -> bool:
  anchor = get_anchor(root)
  for logdir in segment_dirs(root):
    if not in_upload_window(logdir, anchor):
      continue
    for name in RLOG_NAMES:
      fn = os.path.join(root, logdir, name)
      try:
        if os.path.getsize(fn) > 0 and _read_xattr(fn, UPLOAD_ATTR_NAME) != UPLOAD_ATTR_VALUE:
          return True
      except OSError:
        continue
  return False
