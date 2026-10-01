"""Import an Starpilot Auto identity from an app package."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import struct
import tempfile
import threading
import time
import urllib.request
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from openpilot.starpilot.system.starpilot_auto import identity as identity_store

GOOGLE_ROOT_SHA256 = "49e52efc13ad2ed09f204c3b10698bd84bb7105f510558aa14b8119a5c4ad17f"
PACKAGE = "com.google.android.projection.gearhead"
KNOWN_GOOD_VERSION = "17.6.663454-release"
RECOMMENDED_MANIFEST_URL = "https://aa.didesigns.fyi/android-auto/recommended.json"
MAX_MANIFEST_BYTES = 16 * 1024

MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_APK_BYTES = 192 * 1024 * 1024
MAX_DEX_BYTES = 64 * 1024 * 1024
MAX_DEX_FILES = 32
MAX_CANDIDATES = 64
MASK_SIZE = 256
PEM = re.compile(rb"-----BEGIN CERTIFICATE-----[\s\S]{100,8000}?-----END CERTIFICATE-----\n\x00")
FILL_ARRAY_BYTES = re.compile(rb"\x00\x03\x01\x00")
DEX_NAME = re.compile(r"classes\d*\.dex")
IMPORT_DIR = identity_store.DATA_DIR / "import"


class IdentityImportError(RuntimeError):
  pass


# ------------------------------------------------------------------ extraction

def derive_aes_material(cert: bytes, root: bytes, mask: bytes) -> bytes:
  """Key and IV derivation."""
  state = bytearray(48)

  def mix(data):
    for pos in range(len(data)):
      for i in range(48):
        b = state[i]
        # data may alias state in later rounds, so read data[pos] inside the loop
        state[i] = ((((b >> 7) | (b + b)) + 33) ^ mask[i % len(mask)] ^ data[pos]) & 255

  mix(cert)
  mix(root)
  for _ in range(7):
    mix(state)
  return bytes(state)


def _checked_read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, limit: int) -> bytes:
  if info.file_size > limit:
    raise IdentityImportError(f"{info.filename} is too large ({info.file_size // (1024 * 1024)} MB)")
  with archive.open(info) as handle:
    data = handle.read(limit + 1)
  if len(data) > limit:
    raise IdentityImportError(f"{info.filename} is larger than it claims")
  return data


def _dex_files(path: Path) -> tuple[list[bytes], str]:
  """Returns (dexes, description)."""
  if path.stat().st_size > MAX_FILE_BYTES:
    raise IdentityImportError("File is too large to be the Starpilot Auto app")
  try:
    outer = zipfile.ZipFile(path)
  except zipfile.BadZipFile as error:
    raise IdentityImportError("Unrecognized file") from error
  with outer:
    names = [info for info in outer.infolist() if DEX_NAME.fullmatch(info.filename)]
    if names:
      return [_checked_read(outer, info, MAX_DEX_BYTES) for info in names[:MAX_DEX_FILES]], "apk"
    for info in sorted((i for i in outer.infolist() if i.filename.endswith(".apk")),
                       key=lambda i: (PACKAGE not in i.filename and "base" not in i.filename, -i.file_size)):
      inner_bytes = _checked_read(outer, info, MAX_APK_BYTES)
      try:
        inner = zipfile.ZipFile(io.BytesIO(inner_bytes))
      except zipfile.BadZipFile:
        continue
      with inner:
        dex = [i for i in inner.infolist() if DEX_NAME.fullmatch(i.filename)]
        if dex:
          return [_checked_read(inner, i, MAX_DEX_BYTES) for i in dex[:MAX_DEX_FILES]], f"bundle ({info.filename})"
  raise IdentityImportError("No app code found in this file")


def _candidates(dexes: list[bytes]) -> tuple[set[bytes], list[bytes], list[bytes]]:
  pems: set[bytes] = set()
  masks: list[bytes] = []
  blobs: list[bytes] = []
  for dex in dexes:
    pems.update(match.group()[:-1] for match in PEM.finditer(dex))
    for match in FILL_ARRAY_BYTES.finditer(dex):
      if match.start() % 2 or match.end() + 4 > len(dex):
        continue
      size = struct.unpack_from("<I", dex, match.end())[0]
      start = match.end() + 4
      if start + size > len(dex):
        continue
      if size == MASK_SIZE and len(masks) < MAX_CANDIDATES:
        masks.append(dex[start:start + size])
      elif 512 <= size <= 8192 and size % 16 == 0 and len(blobs) < MAX_CANDIDATES:
        blobs.append(dex[start:start + size])
  return pems, masks, blobs


def _not_after(cert):
  return cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=UTC)


def _not_before(cert):
  return cert.not_valid_before_utc if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before.replace(tzinfo=UTC)


def extract_identity(path: Path, *, root_sha256: str = GOOGLE_ROOT_SHA256, now: datetime | None = None,
                     progress: Callable[[str], None] = lambda stage: None) -> tuple[dict[str, bytes], dict]:
  """Returns ({file name: PEM bytes}, metadata)."""
  from cryptography import x509
  from cryptography.hazmat.primitives import padding, serialization
  from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

  progress("reading")
  dexes, source = _dex_files(Path(path))
  progress("searching")
  pems, masks, blobs = _candidates(dexes)
  del dexes
  certs = {}
  for pem in pems:
    try:
      certs[pem] = x509.load_pem_x509_certificate(pem)
    except ValueError:
      continue
  der_sha = {pem: hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest() for pem, cert in certs.items()}
  roots = [pem for pem in certs if der_sha[pem] == root_sha256]
  if not roots:
    raise IdentityImportError("This file is not the Starpilot Auto app")
  root_pem = roots[0]
  root = certs[root_pem]
  leaves = []
  for pem, cert in certs.items():
    if pem == root_pem:
      continue
    try:
      cert.verify_directly_issued_by(root)
      leaves.append(pem)
    except Exception:
      continue
  if not leaves:
    raise IdentityImportError("No phone certificate was found in this file")

  progress("decrypting")
  for leaf_pem in leaves:
    leaf = certs[leaf_pem]
    wanted = leaf.public_key().public_numbers()
    for mask in masks:
      material = derive_aes_material(leaf_pem, root_pem, mask)
      for blob in blobs:
        try:
          decryptor = Cipher(algorithms.AES(material[:32]), modes.CBC(material[32:])).decryptor()
          unpadder = padding.PKCS7(128).unpadder()
          plain = unpadder.update(decryptor.update(blob) + decryptor.finalize()) + unpadder.finalize()
          key = serialization.load_pem_private_key(plain, password=None)
        except Exception:
          continue
        if key.public_key().public_numbers() != wanted:
          continue
        progress("verifying")
        now = now or datetime.now(UTC)
        for cert in (leaf, root):
          if now < _not_before(cert):
            raise IdentityImportError("This app is not valid yet; check the comma's clock")
          if now >= _not_after(cert):
            raise IdentityImportError(f"This app expired on {_not_after(cert).date()}; use a newer Starpilot Auto version")
        pem_key = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        metadata = {
          "subject": leaf.subject.rfc4514_string(),
          "expires": _not_after(leaf).isoformat(),
          "certificate_sha256": der_sha[leaf_pem],
          "root_sha256": der_sha[root_pem],
          "source": source,
          "imported": datetime.now(UTC).isoformat(timespec="seconds"),
          "key_matches": True,
        }
        return {identity_store.CERT_NAME: leaf_pem, identity_store.KEY_NAME: pem_key, identity_store.ROOT_NAME: root_pem}, metadata
  raise IdentityImportError("This Starpilot Auto version is not supported; "
                            f"use version {KNOWN_GOOD_VERSION}")


# ------------------------------------------------------------------ install

def install_identity(files: dict[str, bytes], metadata: dict, directory: Path | None = None) -> None:
  """Replaces the identity directory atomically, keeping the previous one as ``identity.previous``."""
  directory = directory or identity_store.IDENTITY_DIR
  directory.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
  staging = Path(tempfile.mkdtemp(prefix=".identity-", dir=directory.parent))
  try:
    os.chmod(staging, 0o700)
    for name, content in {**files, "provenance.json": (json.dumps(metadata, indent=2) + "\n").encode()}.items():
      with os.fdopen(os.open(staging / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    identity_store.load_identity(staging)
    previous = directory.with_name(directory.name + ".previous")
    replacing = directory.exists()
    if replacing:
      shutil.rmtree(previous, ignore_errors=True)
      os.replace(directory, previous)
    try:
      os.replace(staging, directory)
    except OSError:
      if replacing and previous.exists() and not directory.exists():
        os.replace(previous, directory)
      raise
  except BaseException:
    shutil.rmtree(staging, ignore_errors=True)
    raise


def remove_identity(directory: Path | None = None) -> None:
  directory = directory or identity_store.IDENTITY_DIR
  shutil.rmtree(directory, ignore_errors=True)


def identity_status(directory: Path | None = None) -> dict:
  directory = directory or identity_store.IDENTITY_DIR
  if not (directory / identity_store.CERT_NAME).exists():
    return {"installed": False, "message": "No Starpilot Auto identity installed"}
  try:
    provenance = json.loads((directory / "provenance.json").read_text())
    if not isinstance(provenance, dict):
      provenance = {}
  except (OSError, ValueError):
    provenance = {}
  package_version = provenance.get("package_version", "")
  try:
    ident = identity_store.load_identity(directory)
  except identity_store.IdentityError as error:
    return {"installed": False, "expired": "expired" in str(error), "error": str(error), "message": str(error),
            "package_version": package_version}
  return {
    "installed": True,
    "expires": ident.expires,
    "days_left": ident.days_left,
    "warning": identity_store.expiry_warning(ident),
    "subject": provenance.get("subject", ""),
    "certificate_sha256": provenance.get("certificate_sha256", ""),
    "imported": provenance.get("imported", ""),
    "source": provenance.get("source", ""),
    "package_version": package_version,
  }


# ------------------------------------------------------------------ background import

def download(url: str, destination: Path, progress: Callable[[int, int], None] = lambda done, total: None,
             *, max_bytes: int = MAX_FILE_BYTES, https_only: bool = False) -> None:
  if not url.lower().startswith(("https://", "http://")):
    raise IdentityImportError("Enter an http(s) link to the APK or XAPK")
  if https_only and urlsplit(url).scheme != "https":
    raise IdentityImportError("Recommended downloads require HTTPS")
  request = urllib.request.Request(url, headers={"User-Agent": "StarPilot/1"})
  try:
    with urllib.request.urlopen(request, timeout=30) as response, open(destination, "wb") as handle:
      if https_only and urlsplit(response.geturl()).scheme != "https":
        raise IdentityImportError("Recommended downloads require HTTPS")
      total = int(response.headers.get("Content-Length") or 0)
      if total > max_bytes:
        raise IdentityImportError("That file is too large to be the Starpilot Auto app")
      done = 0
      while chunk := response.read(1024 * 1024):
        done += len(chunk)
        if done > max_bytes:
          raise IdentityImportError("That file is too large to be the Starpilot Auto app")
        handle.write(chunk)
        progress(done, total)
  except IdentityImportError:
    raise
  except Exception as error:
    raise IdentityImportError(f"Download failed: {error}") from error


def validate_recommended_manifest(value: object) -> dict:
  """Validate the small public manifest before fetching or unpacking its package."""
  if not isinstance(value, dict) or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1:
    raise IdentityImportError("Unsupported recommended package manifest")
  version, url, digest = (value.get(key) for key in ("version", "url", "sha256"))
  if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", version):
    raise IdentityImportError("Recommended manifest has an invalid version")
  if not isinstance(url, str) or len(url) > 2048:
    raise IdentityImportError("Recommended manifest has an invalid download URL")
  try:
    parsed = urlsplit(url)
    valid_url = parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment
  except ValueError:
    valid_url = False
  if not valid_url:
    raise IdentityImportError("Recommended manifest requires an HTTPS download URL")
  if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
    raise IdentityImportError("Recommended manifest has an invalid SHA-256 checksum")
  size = value.get("sizeBytes")
  if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
    raise IdentityImportError("Recommended package size is invalid or too large")
  if value.get("format") not in ("apk", "xapk", "apkm", "zip"):
    raise IdentityImportError("Unsupported recommended package format")
  if value["format"] == "zip":
    member = value.get("archiveMember")
    if (not isinstance(member, str) or len(member) > 512 or "\\" in member or
        member.startswith("/") or any(part in ("", ".", "..") for part in member.split("/")) or
        not member.lower().endswith((".apk", ".xapk", ".apkm"))):
      raise IdentityImportError("Recommended manifest has an invalid archive member")
  return value


def download_recommended(destination: Path, progress: Callable[..., None]) -> dict:
  """Fetch, verify and unwrap the recommended app, without touching the installed identity."""
  manifest_path = destination.with_suffix(".manifest")
  unpacked = destination.with_suffix(".unpacked")
  try:
    progress(stage="resolving")
    download(RECOMMENDED_MANIFEST_URL, manifest_path, lambda *_: progress(), max_bytes=MAX_MANIFEST_BYTES, https_only=True)
    try:
      manifest = validate_recommended_manifest(json.loads(manifest_path.read_bytes()))
    except (ValueError, UnicodeError) as error:
      raise IdentityImportError("Could not read the recommended package manifest") from error
    progress(stage="downloading", version=manifest["version"], downloaded=0, total=manifest["sizeBytes"])
    download(manifest["url"], destination, lambda done, _: progress(downloaded=done, total=manifest["sizeBytes"]),
             max_bytes=manifest["sizeBytes"], https_only=True)
    progress(stage="checking_package")
    if destination.stat().st_size != manifest["sizeBytes"]:
      raise IdentityImportError("Recommended download is incomplete; please try again")
    with destination.open("rb") as handle:
      digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != manifest["sha256"].lower():
      raise IdentityImportError("Recommended package checksum does not match; nothing was installed")
    if manifest["format"] == "zip":
      progress(stage="unpacking")
      try:
        with zipfile.ZipFile(destination) as archive:
          matches = [info for info in archive.infolist() if info.filename == manifest["archiveMember"]]
          if len(matches) != 1 or matches[0].is_dir():
            raise IdentityImportError("The recommended app is missing or duplicated in the ZIP")
          if matches[0].file_size > MAX_FILE_BYTES:
            raise IdentityImportError("The unpacked app is too large")
          # Write only the named member to a fixed temporary path, never extractall.
          with archive.open(matches[0]) as source, unpacked.open("wb") as output:
            size = 0
            while chunk := source.read(1024 * 1024):
              progress()
              size += len(chunk)
              if size > MAX_FILE_BYTES:
                raise IdentityImportError("The unpacked app is too large")
              output.write(chunk)
        os.replace(unpacked, destination)
      except IdentityImportError:
        raise
      except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise IdentityImportError("Could not unpack the recommended ZIP") from error
    return manifest
  finally:
    manifest_path.unlink(missing_ok=True)
    unpacked.unlink(missing_ok=True)


class RecommendationCheck:
  """Check on page entry; ordinary status polls only read the cached result."""

  def __init__(self):
    self.lock = threading.Lock()
    self.thread: threading.Thread | None = None
    self.version = ""
    self.error = ""

  def status(self, installed_version: str = "", *, check: bool = False) -> dict:
    with self.lock:
      if check and not (self.thread and self.thread.is_alive()):
        self.thread = threading.Thread(target=self._check, name="starpilot_auto_recommendation", daemon=True)
        self.thread.start()
      version, error = self.version, self.error
      checking = bool(self.thread and self.thread.is_alive())
    # Compare numeric components, so 17.10 is newer than 17.9. Never label a
    # manually installed package with unknown provenance as out of date.
    def numbers(value):
      match = re.fullmatch(r"(\d+(?:\.\d+)*)(?:[-_].*)?", str(value))
      return tuple(int(part) for part in match[1].split(".")) if match else ()
    current, recommended = numbers(installed_version), numbers(version)
    length = max(len(current), len(recommended))
    newer = bool(current and recommended and current + (0,) * (length - len(current)) < recommended + (0,) * (length - len(recommended)))
    return {"version": version, "updateAvailable": newer, "checking": checking, "error": error}

  def _check(self) -> None:
    try:
      with tempfile.TemporaryDirectory(prefix="starpilot_auto-recommendation-") as directory:
        path = Path(directory) / "manifest.json"
        download(RECOMMENDED_MANIFEST_URL, path, max_bytes=MAX_MANIFEST_BYTES, https_only=True)
        manifest = validate_recommended_manifest(json.loads(path.read_bytes()))
      with self.lock:
        self.version, self.error = manifest["version"], ""
    except Exception:
      with self.lock:
        # Keep the last known recommendation; a connectivity problem must not
        # change installation status or expose the download address in the UI.
        self.error = "Could not check for updates. Reopen this page to try again."


class ImportJob:
  """One import at a time, in a background thread, with pollable status."""

  def __init__(self, work_dir: Path | None = None, identity_dir: Path | None = None, root_sha256: str = GOOGLE_ROOT_SHA256):
    self.work_dir = work_dir or IMPORT_DIR
    self.identity_dir = identity_dir
    self.root_sha256 = root_sha256
    self.lock = threading.Lock()
    self.thread: threading.Thread | None = None
    self.state: dict = {"state": "idle"}

  def status(self) -> dict:
    with self.lock:
      return dict(self.state)

  def _set(self, **values) -> None:
    with self.lock:
      self.state.update(values)

  def busy(self) -> bool:
    return self.thread is not None and self.thread.is_alive()

  def upload_path(self) -> Path:
    self.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    return self.work_dir / "starpilot-auto-upload.bin"

  def reserve_upload_path(self) -> Path:
    """A private file for one upload request, so a rejected request cannot overwrite the import in progress."""
    self.work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix="upload-", suffix=".bin", dir=self.work_dir)
    os.close(descriptor)
    return Path(name)

  def start(self, *, path: Path | None = None, url: str = "", enabled=None, recommended: bool = False) -> None:
    with self.lock:  # check and claim together, so two requests cannot both start
      if self.busy():
        raise IdentityImportError("An import is already running")
      self.state = {"state": "running", "stage": "resolving" if recommended else "downloading" if url else "reading", "started": time.time(),
                    "downloaded": 0, "total": 0}
      self.thread = threading.Thread(target=self._run, args=(path, url, enabled, recommended), name="starpilot_auto_identity_import", daemon=True)
      self.thread.start()

  def _run(self, path: Path | None, url: str, enabled=None, recommended: bool = False) -> None:
    def progress(**values):
      if enabled is not None and not enabled():
        raise IdentityImportError("Import cancelled: Starpilot Auto is disabled")
      self._set(**values)

    source = path
    try:
      source = source or self.upload_path()
      progress()
      manifest = None
      if recommended:
        manifest = download_recommended(source, progress)
      elif url:
        download(url, source, lambda done, total: progress(downloaded=done, total=total))
      files, metadata = extract_identity(source, root_sha256=self.root_sha256, progress=lambda stage: progress(stage=stage))
      if manifest:
        metadata.update(package_version=manifest["version"], package_sha256=manifest["sha256"], package_url=manifest["url"])
      progress(stage="installing")
      install_identity(files, metadata, self.identity_dir)
      self._set(state="done", stage="done", finished=time.time(), expires=metadata["expires"],
                message=f"Identity installed; valid until {metadata['expires'][:10]}")
    except IdentityImportError as error:
      self._set(state="failed", finished=time.time(), error=str(error))
    except Exception as error:
      self._set(state="failed", finished=time.time(), error=f"{type(error).__name__}: {error}")
    finally:
      try:
        if source is not None:
          source.unlink(missing_ok=True)
      except OSError:
        pass
