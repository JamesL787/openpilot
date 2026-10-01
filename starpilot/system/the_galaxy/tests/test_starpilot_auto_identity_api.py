import io

import test_navigation_params as nav
from openpilot.starpilot.system.starpilot_auto import apk_identity, identity as identity_store
from openpilot.starpilot.system.starpilot_auto.tests.test_apk_identity import build_identity, encrypt_key, make_xapk


def _client(monkeypatch, tmp_path):
  cert, root, key_pem, root_sha = build_identity()
  mask = bytes(range(256))
  ident = {"cert": cert, "root": root, "key": key_pem, "root_sha": root_sha, "mask": mask,
           "blob": encrypt_key(cert, root, mask, key_pem)}
  monkeypatch.setattr(identity_store, "IDENTITY_DIR", tmp_path / "starpilot_auto" / "identity")
  monkeypatch.setattr(apk_identity, "IMPORT_DIR", tmp_path / "starpilot_auto" / "import")
  real_job = apk_identity.ImportJob
  monkeypatch.setattr(nav.the_galaxy.apk_identity, "ImportJob", lambda: real_job(root_sha256=root_sha))
  client, _ = nav._params_client(monkeypatch, {"IsOffroad": True, "StarpilotAutoEnabled": True}, "mici")
  return client, ident


def _wait_done(client):
  import time
  deadline = time.monotonic() + 30
  while True:
    payload = client.get("/api/starpilot_auto/identity").get_json()
    if payload["job"]["state"] != "running":
      return payload
    assert time.monotonic() < deadline, payload
    time.sleep(0.05)


def test_identity_upload_installs_and_remove_clears(monkeypatch, tmp_path):
  client, ident = _client(monkeypatch, tmp_path)
  response = client.get("/api/starpilot_auto/identity")
  assert response.status_code == 200 and response.headers["Cache-Control"].startswith("no-store")
  assert response.get_json()["installed"] is False and response.get_json()["knownGoodVersion"]

  data = {"apk": (io.BytesIO(make_xapk(tmp_path, ident).read_bytes()), "starpilot-auto.xapk")}
  response = client.post("/api/starpilot_auto/identity/upload", data=data, content_type="multipart/form-data")
  assert response.status_code == 202
  payload = _wait_done(client)
  assert payload["job"]["state"] == "done" and payload["installed"] is True and payload["days_left"] > 300
  assert (tmp_path / "starpilot_auto" / "identity" / "phone-key.pem").exists()

  assert client.delete("/api/starpilot_auto/identity").get_json()["installed"] is False


def test_identity_upload_rejects_wrong_file_and_bad_link(monkeypatch, tmp_path):
  client, _ = _client(monkeypatch, tmp_path)
  assert client.post("/api/starpilot_auto/identity/upload", data={}, content_type="multipart/form-data").status_code == 400

  data = {"apk": (io.BytesIO(b"not an apk"), "photo.jpg")}
  assert client.post("/api/starpilot_auto/identity/upload", data=data, content_type="multipart/form-data").status_code == 202
  payload = _wait_done(client)
  assert payload["job"]["state"] == "failed" and "Unrecognized file" in payload["job"]["error"] and payload["installed"] is False

  assert client.post("/api/starpilot_auto/identity/download", json={"url": "file:///etc/passwd"}).status_code == 400
