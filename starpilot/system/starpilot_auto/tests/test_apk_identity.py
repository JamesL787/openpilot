import datetime
import hashlib
import http.server
import io
import json
import os
import struct
import threading
import zipfile
from pathlib import Path

import pytest

from openpilot.starpilot.system.starpilot_auto import apk_identity, identity as identity_store

REAL_XAPK = Path(__file__).resolve().parents[4] / ".cache/starpilot_auto/starpilot-auto-17-6-663454-release.xapk"


def build_identity(days=365):
  from cryptography import x509
  from cryptography.hazmat.primitives import hashes, serialization
  from cryptography.hazmat.primitives.asymmetric import rsa
  from cryptography.x509.oid import NameOID

  now = datetime.datetime.now(datetime.UTC)

  def name(org):
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org)])

  root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
  root = (x509.CertificateBuilder().subject_name(name("Google Automotive Link")).issuer_name(name("Google Automotive Link"))
          .public_key(root_key.public_key()).serial_number(1).not_valid_before(now - datetime.timedelta(days=1))
          .not_valid_after(now + datetime.timedelta(days=3650)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
          .sign(root_key, hashes.SHA256()))
  leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
  leaf = (x509.CertificateBuilder().subject_name(name("CarService")).issuer_name(root.subject).public_key(leaf_key.public_key())
          .serial_number(2).not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=days))
          .sign(root_key, hashes.SHA256()))
  pem = serialization.Encoding.PEM
  key_pem = leaf_key.private_bytes(pem, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
  root_sha = hashlib.sha256(root.public_bytes(serialization.Encoding.DER)).hexdigest()
  return leaf.public_bytes(pem), root.public_bytes(pem), key_pem, root_sha


def encrypt_key(cert, root, mask, key_pem):
  from cryptography.hazmat.primitives import padding
  from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
  material = apk_identity.derive_aes_material(cert, root, mask)
  padder = padding.PKCS7(128).padder()
  padded = padder.update(key_pem) + padder.finalize()
  encryptor = Cipher(algorithms.AES(material[:32]), modes.CBC(material[32:])).encryptor()
  return encryptor.update(padded) + encryptor.finalize()


def fill_array(data: bytes) -> bytes:
  return b"\x00\x03\x01\x00" + struct.pack("<I", len(data)) + data + (b"\x00" if len(data) % 2 else b"")


def fake_dex(*parts: bytes) -> bytes:
  out = bytearray(b"dex\n035\x00" + bytes(24))
  for part in parts:
    if len(out) % 2:
      out += b"\x00"
    out += part
  return bytes(out)


def string_item(text: bytes) -> bytes:
  return bytes([min(len(text), 127)]) + text + b"\x00"


@pytest.fixture(scope="module")
def ident():
  cert, root, key_pem, root_sha = build_identity()
  mask = bytes(range(256))
  blob = encrypt_key(cert, root, mask, key_pem)
  return {"cert": cert, "root": root, "key": key_pem, "root_sha": root_sha, "mask": mask, "blob": blob}


def make_apk(tmp_path, ident, *, name="app.apk", mask=None):
  mask = ident["mask"] if mask is None else mask
  decoy_mask = bytes(reversed(range(256)))
  dex1 = fake_dex(string_item(b"hello"), fill_array(decoy_mask), string_item(ident["cert"]), fill_array(bytes(1024)))
  dex2 = fake_dex(fill_array(mask), string_item(ident["root"]), fill_array(ident["blob"]))
  path = tmp_path / name
  with zipfile.ZipFile(path, "w") as apk:
    apk.writestr("AndroidManifest.xml", b"manifest")
    apk.writestr("classes.dex", dex1)
    apk.writestr("classes2.dex", dex2)
  return path


def make_xapk(tmp_path, ident):
  base = make_apk(tmp_path, ident, name="base-inner.apk").read_bytes()
  path = tmp_path / "app.xapk"
  with zipfile.ZipFile(path, "w") as xapk:
    xapk.writestr("config.arm64_v8a.apk", b"PK\x05\x06" + bytes(18))  # an empty split
    xapk.writestr("com.google.android.projection.gearhead.apk", base)
    xapk.writestr("manifest.json", b"{}")
  return path


def test_imports_from_apk_and_xapk(tmp_path, ident):
  stages = []
  for path in (make_apk(tmp_path, ident), make_xapk(tmp_path, ident)):
    files, meta = apk_identity.extract_identity(path, root_sha256=ident["root_sha"], progress=stages.append)
    assert files["phone-cert.pem"] == ident["cert"] and files["root-cert.pem"] == ident["root"]
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    assert load_pem_private_key(files["phone-key.pem"], None).private_numbers() == load_pem_private_key(ident["key"], None).private_numbers()
    assert meta["key_matches"] and meta["root_sha256"] == ident["root_sha"]
  assert stages[:4] == ["reading", "searching", "decrypting", "verifying"]


def test_rejects_identity_not_from_google_root(tmp_path, ident):
  with pytest.raises(apk_identity.IdentityImportError, match="is not the Starpilot Auto app"):
    apk_identity.extract_identity(make_apk(tmp_path, ident))  # the real pinned root, not the fixture's


def test_rejects_when_no_key_is_recovered(tmp_path, ident):
  path = make_apk(tmp_path, ident, mask=bytes(256))
  with pytest.raises(apk_identity.IdentityImportError, match="not supported"):
    apk_identity.extract_identity(path, root_sha256=ident["root_sha"])


def test_rejects_expired_certificate(tmp_path, ident):
  later = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=400)
  with pytest.raises(apk_identity.IdentityImportError, match="expired"):
    apk_identity.extract_identity(make_apk(tmp_path, ident), root_sha256=ident["root_sha"], now=later)


def test_rejects_non_apk_and_oversized_code(tmp_path, ident, monkeypatch):
  junk = tmp_path / "junk.apk"
  junk.write_bytes(b"not a zip")
  with pytest.raises(apk_identity.IdentityImportError, match="Unrecognized file"):
    apk_identity.extract_identity(junk)
  empty = tmp_path / "empty.apk"
  with zipfile.ZipFile(empty, "w") as z:
    z.writestr("readme.txt", "hi")
  with pytest.raises(apk_identity.IdentityImportError, match="No app code"):
    apk_identity.extract_identity(empty)
  monkeypatch.setattr(apk_identity, "MAX_DEX_BYTES", 64)
  with pytest.raises(apk_identity.IdentityImportError, match="too large"):
    apk_identity.extract_identity(make_apk(tmp_path, ident), root_sha256=ident["root_sha"])


def test_install_is_atomic_and_keeps_previous(tmp_path, ident):
  directory = tmp_path / "starpilot_auto" / "identity"
  files = {"phone-cert.pem": ident["cert"], "phone-key.pem": ident["key"], "root-cert.pem": ident["root"]}
  apk_identity.install_identity(files, {"expires": "x"}, directory)
  assert apk_identity.identity_status(directory)["installed"]
  assert oct(os.stat(directory).st_mode & 0o777) == "0o700" and oct(os.stat(directory / "phone-key.pem").st_mode & 0o777) == "0o600"
  other_cert, other_root, _, _ = build_identity()
  with pytest.raises(identity_store.IdentityError):  # key does not match the certificate: nothing changes
    apk_identity.install_identity({**files, "phone-cert.pem": other_cert, "root-cert.pem": other_root}, {}, directory)
  assert (directory / "phone-cert.pem").read_bytes() == ident["cert"]
  assert not [p for p in directory.parent.iterdir() if p.name.startswith(".identity-")]
  apk_identity.install_identity(files, {"expires": "y"}, directory)
  assert (directory.parent / "identity.previous" / "phone-cert.pem").exists()
  apk_identity.remove_identity(directory)
  assert apk_identity.identity_status(directory) == {"installed": False, "message": "No Starpilot Auto identity installed"}


def test_import_stops_when_master_switch_is_disabled(monkeypatch, tmp_path):
  source = tmp_path / "upload.apk"
  source.write_bytes(b"test")
  enabled = {"value": True}

  def extract(*args, progress, **kwargs):
    enabled["value"] = False
    progress("reading")
    pytest.fail("disabled import continued")

  monkeypatch.setattr(apk_identity, "extract_identity", extract)
  monkeypatch.setattr(apk_identity, "install_identity", lambda *a: pytest.fail("disabled import installed a certificate"))
  job = apk_identity.ImportJob(work_dir=tmp_path)
  job.start(path=source, enabled=lambda: enabled["value"])
  job.thread.join(timeout=5)
  assert not job.busy()
  assert "disabled" in job.status()["error"]
  assert not source.exists()


def test_install_restores_previous_if_final_replace_fails(monkeypatch, tmp_path, ident):
  directory = tmp_path / "identity"
  files = {"phone-cert.pem": ident["cert"], "phone-key.pem": ident["key"], "root-cert.pem": ident["root"]}
  apk_identity.install_identity(files, {"original": True}, directory)
  original = apk_identity.os.replace

  def fail_final(source, target):
    if Path(source).name.startswith(".identity-"):
      raise OSError("simulated install failure")
    original(source, target)

  monkeypatch.setattr(apk_identity.os, "replace", fail_final)
  with pytest.raises(OSError, match="simulated"):
    apk_identity.install_identity(files, {"original": False}, directory)
  assert apk_identity.identity_status(directory)["installed"]
  assert json.loads((directory / "provenance.json").read_text()) == {"original": True}
  assert not list(tmp_path.glob(".identity-*"))


def test_status_reports_expiry(tmp_path):
  cert, root, key_pem, _ = build_identity(days=5)
  directory = tmp_path / "identity"
  apk_identity.install_identity({"phone-cert.pem": cert, "phone-key.pem": key_pem, "root-cert.pem": root}, {"subject": "O=CarService"}, directory)
  status = apk_identity.identity_status(directory)
  assert status["installed"] and status["days_left"] in (4, 5) and "renew" in status["warning"]


def wait_job(job):
  job.thread.join(30)
  return job.status()


def test_import_job_from_upload_and_from_link(tmp_path, ident):
  directory = tmp_path / "starpilot_auto" / "identity"
  job = apk_identity.ImportJob(work_dir=tmp_path / "work", identity_dir=directory, root_sha256=ident["root_sha"])
  job.upload_path().write_bytes(make_xapk(tmp_path, ident).read_bytes())
  job.start()
  status = wait_job(job)
  assert status["state"] == "done", status
  assert apk_identity.identity_status(directory)["installed"] and not job.upload_path().exists()

  served = make_apk(tmp_path, ident).read_bytes()

  class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
      self.send_response(200)
      self.send_header("Content-Length", str(len(served)))
      self.end_headers()
      self.wfile.write(served)

    def log_message(self, *args):
      pass

  server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
  threading.Thread(target=server.serve_forever, daemon=True).start()
  try:
    job.start(url=f"http://127.0.0.1:{server.server_port}/starpilot_auto.apk")
    status = wait_job(job)
    assert status["state"] == "done" and status["downloaded"] == len(served), status
  finally:
    server.shutdown()
    server.server_close()
  job.start(url="ftp://example.com/starpilot_auto.apk")
  status = wait_job(job)
  assert status["state"] == "failed" and "http(s)" in status["error"]


def recommended_fixture(monkeypatch, tmp_path, ident, *, wrapped=True, changes=None, member=None):
  app = make_xapk(tmp_path, ident).read_bytes()
  data = app
  if wrapped:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
      archive.writestr(member or "starpilot-auto.xapk", app)
      archive.writestr("__MACOSX/._starpilot-auto.xapk", b"ignored")
    data = buffer.getvalue()
  manifest = {"schemaVersion": 1, "version": "17.6.663454", "url": "https://example.test/app",
              "sizeBytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "format": "zip" if wrapped else "xapk", "archiveMember": "starpilot-auto.xapk", **(changes or {})}
  stages = []

  class Response(io.BytesIO):
    headers = {}

    def geturl(self):
      return "https://example.test/file"

  def fetch(request, **kwargs):
    return Response(json.dumps(manifest).encode() if request.full_url == apk_identity.RECOMMENDED_MANIFEST_URL else data)

  monkeypatch.setattr(apk_identity.urllib.request, "urlopen", fetch)
  job = apk_identity.ImportJob(work_dir=tmp_path / "work", identity_dir=tmp_path / "identity", root_sha256=ident["root_sha"])
  original = job._set

  def record(**values):
    if "stage" in values:
      stages.append(values["stage"])
    original(**values)

  monkeypatch.setattr(job, "_set", record)
  return job, stages


@pytest.mark.parametrize("wrapped", [True, False])
def test_recommended_installs_verified_package_and_cleans_up(monkeypatch, tmp_path, ident, wrapped):
  job, stages = recommended_fixture(monkeypatch, tmp_path, ident, wrapped=wrapped)
  job.start(recommended=True)
  result = wait_job(job)
  assert result["state"] == "done", result
  assert "checking_package" in stages and ("unpacking" in stages) == wrapped
  assert apk_identity.identity_status(job.identity_dir)["installed"]
  assert json.loads((job.identity_dir / "provenance.json").read_text())["package_version"] == "17.6.663454"
  assert list(job.work_dir.iterdir()) == []


@pytest.mark.parametrize("changes,member,error", [
  ({"sha256": "0" * 64}, None, "checksum"),
  ({"sizeBytes": 1}, None, "too large"),
  ({"sizeBytes": apk_identity.MAX_FILE_BYTES}, None, "incomplete"),
  ({}, "wrong.xapk", "missing"),
  ({"archiveMember": "../outside.xapk"}, None, "archive member"),
  ({"url": "http://example.test/app"}, None, "HTTPS"),
  ({"schemaVersion": 2}, None, "Unsupported"),
])
def test_recommended_failure_preserves_existing_identity(monkeypatch, tmp_path, ident, changes, member, error):
  job, _ = recommended_fixture(monkeypatch, tmp_path, ident, changes=changes, member=member)
  apk_identity.install_identity({"phone-cert.pem": ident["cert"], "phone-key.pem": ident["key"], "root-cert.pem": ident["root"]},
                                {"original": True}, job.identity_dir)
  before = {p.name: p.read_bytes() for p in job.identity_dir.iterdir()}
  job.start(recommended=True)
  result = wait_job(job)
  assert result["state"] == "failed" and error in result["error"], result
  assert {p.name: p.read_bytes() for p in job.identity_dir.iterdir()} == before
  assert list(job.work_dir.iterdir()) == []


def test_recommended_cancel_and_busy(monkeypatch, tmp_path, ident):
  job, _ = recommended_fixture(monkeypatch, tmp_path, ident)
  entered, release = threading.Event(), threading.Event()

  def enabled():
    entered.set()
    release.wait(5)
    return False

  job.start(recommended=True, enabled=enabled)
  assert entered.wait(5)
  try:
    with pytest.raises(apk_identity.IdentityImportError, match="already running"):
      job.start(recommended=True)
  finally:
    release.set()
  assert "disabled" in wait_job(job)["error"]
  assert not job.identity_dir.exists() and list(job.work_dir.iterdir()) == []


def test_recommended_bounds_manifest_download(monkeypatch, tmp_path, ident):
  job, _ = recommended_fixture(monkeypatch, tmp_path, ident)

  class Response(io.BytesIO):
    headers = {}

    def geturl(self):
      return apk_identity.RECOMMENDED_MANIFEST_URL

  monkeypatch.setattr(apk_identity.urllib.request, "urlopen", lambda *a, **k: Response(b" " * (apk_identity.MAX_MANIFEST_BYTES + 1)))
  job.start(recommended=True)
  assert "too large" in wait_job(job)["error"]
  assert list(job.work_dir.iterdir()) == []


def test_recommendation_only_checks_on_request_and_compares_versions(monkeypatch, tmp_path, ident):
  recommended_fixture(monkeypatch, tmp_path, ident, changes={"version": "17.10.1"})
  checker = apk_identity.RecommendationCheck()
  assert checker.status()["version"] == "" and checker.thread is None
  checker.status(check=True)
  checker.thread.join(5)
  thread = checker.thread
  assert checker.status("17.9.999")["updateAvailable"]
  assert not checker.status("17.10.1-release")["updateAvailable"]
  assert not checker.status("18.0")["updateAvailable"]
  assert not checker.status("")["updateAvailable"]
  assert checker.thread is thread, "status polling must never launch a check"
  checker.status(check=True)
  checker.thread.join(5)
  assert checker.thread is not thread, "reopening checks again"


def test_recommendation_failure_does_not_retry_from_status_polls(monkeypatch):
  calls = []

  def offline(*args, **kwargs):
    calls.append(True)
    raise OSError("offline")

  monkeypatch.setattr(apk_identity, "download", offline)
  checker = apk_identity.RecommendationCheck()
  checker.status(check=True)
  checker.thread.join(5)
  for _ in range(5):
    assert "Reopen" in checker.status()["error"]
  assert len(calls) == 1


@pytest.mark.skipif(not REAL_XAPK.exists(), reason="the user's own Starpilot Auto XAPK is not in .cache/")
def test_real_starpilot_auto_17_6_xapk():
  files, meta = apk_identity.extract_identity(REAL_XAPK)
  assert meta["root_sha256"] == apk_identity.GOOGLE_ROOT_SHA256 and "CarService" in meta["subject"]
  assert set(files) == {"phone-cert.pem", "phone-key.pem", "root-cert.pem"}


def test_concurrent_uploads_never_share_a_file(tmp_path, monkeypatch):
  import threading
  job = apk_identity.ImportJob(work_dir=tmp_path / "work", identity_dir=tmp_path / "identity")
  release = threading.Event()
  monkeypatch.setattr(job, "_run", lambda *a, **k: release.wait(10))
  first, second = job.reserve_upload_path(), job.reserve_upload_path()
  assert first != second and first.parent == second.parent == tmp_path / "work"
  first.write_bytes(b"first")
  job.start(path=first)
  second.write_bytes(b"second")
  with pytest.raises(apk_identity.IdentityImportError):
    job.start(path=second)  # the rejected request only ever wrote its own file
  assert first.read_bytes() == b"first"
  release.set()
  job.thread.join(5)
