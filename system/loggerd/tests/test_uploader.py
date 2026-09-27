import os
import time
import threading
import logging
import json
from pathlib import Path
from openpilot.system.hardware.hw import Paths

from openpilot.common.swaglog import cloudlog
from openpilot.system.loggerd.rlog_upload import clear_anchor, current_route, get_anchor, rlogs_pending
from openpilot.system.loggerd.uploader import Uploader, clear_locks, main, UPLOAD_ATTR_NAME, UPLOAD_ATTR_VALUE
from openpilot.system.loggerd.xattr_cache import getxattr, setxattr

from openpilot.system.loggerd.tests.loggerd_tests_common import UploaderTestCase


class FakeLogHandler(logging.Handler):
  def __init__(self):
    logging.Handler.__init__(self)
    self.reset()

  def reset(self):
    self.upload_order = list()
    self.upload_ignored = list()

  def emit(self, record):
    try:
      j = json.loads(record.getMessage())
      if j["event"] == "upload_success":
        self.upload_order.append(j["key"])
      if j["event"] == "upload_ignored":
        self.upload_ignored.append(j["key"])
    except Exception:
      pass

log_handler = FakeLogHandler()
cloudlog.addHandler(log_handler)


def test_clear_locks_missing_root(tmp_path):
  clear_locks(str(tmp_path / "missing"))


class TestUploader(UploaderTestCase):
  def setup_method(self):
    super().setup_method()
    log_handler.reset()
    # UploadRlogs defaults on in StarPilot; the upstream tests cover qlog-only uploading
    self.params.put_bool("UploadRlogs", False)
    clear_anchor(Paths.log_root())

  def start_thread(self):
    self.end_event = threading.Event()
    self.up_thread = threading.Thread(target=main, args=[self.end_event])
    self.up_thread.daemon = True
    self.up_thread.start()

  def join_thread(self):
    self.end_event.set()
    self.up_thread.join()

  def gen_files(self, lock=False, xattr: bytes = None, boot=True) -> list[Path]:
    f_paths = []
    for t in ["qlog", "rlog", "dcamera.hevc", "fcamera.hevc"]:
      f_paths.append(self.make_file_with_data(self.seg_dir, t, 1, lock=lock, upload_xattr=xattr))

    if boot:
      f_paths.append(self.make_file_with_data("boot", f"{self.seg_dir}", 1, lock=lock, upload_xattr=xattr))
    return f_paths

  def gen_order(self, seg1: list[int], seg2: list[int], boot=True) -> list[str]:
    keys = []
    if boot:
      keys += [f"boot/{self.seg_format.format(i)}.zst" for i in seg1]
      keys += [f"boot/{self.seg_format2.format(i)}.zst" for i in seg2]
    keys += [f"{self.seg_format.format(i)}/qlog.zst" for i in seg1]
    keys += [f"{self.seg_format2.format(i)}/qlog.zst" for i in seg2]
    return keys

  def test_upload(self):
    self.gen_files(lock=False)

    self.start_thread()
    # allow enough time that files could upload twice if there is a bug in the logic
    time.sleep(1)
    self.join_thread()

    exp_order = self.gen_order([self.seg_num], [])

    assert len(log_handler.upload_ignored) == 0, "Some files were ignored"
    assert not len(log_handler.upload_order) < len(exp_order), "Some files failed to upload"
    assert not len(log_handler.upload_order) > len(exp_order), "Some files were uploaded twice"
    for f_path in exp_order:
      assert getxattr((Path(Paths.log_root()) / f_path).with_suffix(""), UPLOAD_ATTR_NAME) == UPLOAD_ATTR_VALUE, "All files not uploaded"

    assert log_handler.upload_order == exp_order, "Files uploaded in wrong order"

  def test_upload_with_wrong_xattr(self):
    self.gen_files(lock=False, xattr=b'0')

    self.start_thread()
    # allow enough time that files could upload twice if there is a bug in the logic
    time.sleep(1)
    self.join_thread()

    exp_order = self.gen_order([self.seg_num], [])

    assert len(log_handler.upload_ignored) == 0, "Some files were ignored"
    assert not len(log_handler.upload_order) < len(exp_order), "Some files failed to upload"
    assert not len(log_handler.upload_order) > len(exp_order), "Some files were uploaded twice"
    for f_path in exp_order:
      assert getxattr((Path(Paths.log_root()) / f_path).with_suffix(""), UPLOAD_ATTR_NAME) == UPLOAD_ATTR_VALUE, "All files not uploaded"

    assert log_handler.upload_order == exp_order, "Files uploaded in wrong order"

  def test_upload_ignored(self):
    self.set_ignore()
    self.gen_files(lock=False)

    self.start_thread()
    # allow enough time that files could upload twice if there is a bug in the logic
    time.sleep(1)
    self.join_thread()

    exp_order = self.gen_order([self.seg_num], [])

    assert len(log_handler.upload_order) == 0, "Some files were not ignored"
    assert not len(log_handler.upload_ignored) < len(exp_order), "Some files failed to ignore"
    assert not len(log_handler.upload_ignored) > len(exp_order), "Some files were ignored twice"
    for f_path in exp_order:
      assert getxattr((Path(Paths.log_root()) / f_path).with_suffix(""), UPLOAD_ATTR_NAME) == UPLOAD_ATTR_VALUE, "All files not ignored"

    assert log_handler.upload_ignored == exp_order, "Files ignored in wrong order"

  def test_upload_files_in_create_order(self):
    seg1_nums = [0, 1, 2, 10, 20]
    for i in seg1_nums:
      self.seg_dir = self.seg_format.format(i)
      self.gen_files(boot=False)
    seg2_nums = [5, 50, 51]
    for i in seg2_nums:
      self.seg_dir = self.seg_format2.format(i)
      self.gen_files(boot=False)

    exp_order = self.gen_order(seg1_nums, seg2_nums, boot=False)

    self.start_thread()
    # allow enough time that files could upload twice if there is a bug in the logic
    time.sleep(1)
    self.join_thread()

    assert len(log_handler.upload_ignored) == 0, "Some files were ignored"
    assert not len(log_handler.upload_order) < len(exp_order), "Some files failed to upload"
    assert not len(log_handler.upload_order) > len(exp_order), "Some files were uploaded twice"
    for f_path in exp_order:
      assert getxattr((Path(Paths.log_root()) / f_path).with_suffix(""), UPLOAD_ATTR_NAME) == UPLOAD_ATTR_VALUE, "All files not uploaded"

    assert log_handler.upload_order == exp_order, "Files uploaded in wrong order"

  def test_no_upload_with_lock_file(self):
    self.start_thread()

    time.sleep(0.25)
    f_paths = self.gen_files(lock=True, boot=False)

    # allow enough time that files should have been uploaded if they would be uploaded
    time.sleep(1)
    self.join_thread()

    for f_path in f_paths:
      fn = f_path.with_suffix(f_path.suffix.replace(".zst", ""))
      uploaded = getxattr(fn, UPLOAD_ATTR_NAME) == UPLOAD_ATTR_VALUE
      assert not uploaded, "File upload when locked"

  def test_no_upload_with_xattr(self):
    self.gen_files(lock=False, xattr=UPLOAD_ATTR_VALUE)

    self.start_thread()
    # allow enough time that files could upload twice if there is a bug in the logic
    time.sleep(1)
    self.join_thread()

    assert len(log_handler.upload_order) == 0, "File uploaded again"

  def test_clear_locks_on_startup(self):
    f_paths = self.gen_files(lock=True, boot=False)
    self.start_thread()
    time.sleep(0.25)
    self.join_thread()

    for f_path in f_paths:
      lock_path = f_path.with_suffix(f_path.suffix + ".lock")
      assert not lock_path.is_file(), "File lock not cleared on startup"

  # StarPilot variables
  def test_rlogs_not_uploaded_when_off(self):
    self.gen_files(lock=False, boot=False)
    self.params.put_bool("UploadRlogs", False)
    self.start_thread()
    time.sleep(1)
    self.join_thread()

    assert log_handler.upload_order == [f"{self.seg_dir}/qlog.zst"]

  def test_upload_rlogs_after_qlogs(self):
    seg2_dir = self.seg_format2.format(self.seg_num)
    self.gen_files(lock=False, boot=False)
    for t in ["qlog", "rlog", "fcamera.hevc"]:
      self.make_file_with_data(seg2_dir, t, 1)
    self.params.put_bool("UploadRlogs", True)
    self.start_thread()
    time.sleep(1)
    self.join_thread()

    # all qlogs first, then rlogs from the drive in progress when the toggle was first seen on
    assert log_handler.upload_order == [f"{self.seg_dir}/qlog.zst", f"{seg2_dir}/qlog.zst", f"{seg2_dir}/rlog.zst"]

  def drain(self, up):
    order = []
    while (f := up.next_file_to_upload(metered=False)) is not None:
      assert rlogs_pending(Paths.log_root())
      order.append(f[1])
      setxattr(f[2], UPLOAD_ATTR_NAME, UPLOAD_ATTR_VALUE)
    return order

  def test_upload_rlogs_previous_drive_then_current_never_backlog(self):
    # route 284: an old route's rlog backlog took the whole drive and the drive's own rlogs never went up
    seg_format3 = "00000006--1109db7c4c--{}"
    for i in [0, 1, 2]:
      self.make_file_with_data(self.seg_format.format(i), "rlog", 1)  # backlog from before the toggle
    for i in [0, 1]:
      self.make_file_with_data(self.seg_format2.format(i), "rlog", 1)  # drive in progress when turned on
    self.params.put_bool("UploadRlogs", True)
    up = Uploader("0000000000000000", Paths.log_root())
    assert up.next_file_to_upload(metered=False)[1] == f"{self.seg_format2.format(0)}/rlog"
    assert get_anchor(Paths.log_root()) == current_route(Paths.log_root()) == self.seg_format2.rpartition('--')[0]

    # a new drive starts before the previous one is done: the previous drive finishes first
    for i in [2, 10]:
      self.make_file_with_data(self.seg_format2.format(i), "rlog", 1)
    for i in [1, 0]:
      self.make_file_with_data(seg_format3.format(i), "rlog", 1)
    assert self.drain(up) == [f"{self.seg_format2.format(i)}/rlog" for i in [0, 1, 2, 10]] + \
                             [f"{seg_format3.format(i)}/rlog" for i in [0, 1]]
    assert not rlogs_pending(Paths.log_root()), "the pre-toggle backlog must not hold shutdown"

  def test_upload_rlogs_off_clears_anchor(self):
    self.make_file_with_data(self.seg_format.format(0), "rlog", 1)
    self.params.put_bool("UploadRlogs", True)
    up = Uploader("0000000000000000", Paths.log_root())
    assert up.next_file_to_upload(metered=False)[1] == f"{self.seg_format.format(0)}/rlog"

    self.params.put_bool("UploadRlogs", False)
    assert up.next_file_to_upload(metered=False) is None
    assert get_anchor(Paths.log_root()) is None and not rlogs_pending(Paths.log_root())

    # back on later: starts again at the newest drive, the one left unsent is backlog now
    self.make_file_with_data(self.seg_format2.format(0), "rlog", 1)
    self.params.put_bool("UploadRlogs", True)
    assert self.drain(up) == [f"{self.seg_format2.format(0)}/rlog"]

  def test_upload_rlogs_skips_locked_uploads_metered(self):
    self.gen_files(lock=True, boot=False)
    self.params.put_bool("UploadRlogs", True)
    up = Uploader("0000000000000000", Paths.log_root())
    assert up.next_file_to_upload(metered=False) is None, "locked (in-progress) segment uploaded"

    clear_locks(Paths.log_root())
    assert up.next_file_to_upload(metered=False)[0] == "qlog"
    setxattr(str(Path(Paths.log_root()) / self.seg_dir / "qlog"), UPLOAD_ATTR_NAME, UPLOAD_ATTR_VALUE)
    # phone hotspots report metered; the owner uploads rlogs over one
    assert up.next_file_to_upload(metered=True)[0] == "rlog"
    assert up.next_file_to_upload(metered=False)[0] == "rlog"
