"""Optional real-browser checks: run with pytest + Playwright and its browsers installed.

UI_STREAM_BROWSER selects chromium (default) or webkit. No comma is required:
two localhost origins serve the real Vue wrapper/viewer with synthetic frames.
"""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[4]
SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" width="2160" height="1080" viewBox="0 0 2160 1080">
<rect width="2160" height="1080" fill="#121a23"/><path d="M650 1080L1000 200M1510 1080L1160 200" stroke="#60df9d" stroke-width="32"/>
<text x="1080" y="160" text-anchor="middle" fill="white" font-size="120">71 mph</text>
<text x="1080" y="930" text-anchor="middle" fill="white" font-size="70">Synthetic UI test frame</text></svg>'''


@pytest.fixture(scope="module")
def browser():
  playwright = pytest.importorskip("playwright.sync_api")
  with playwright.sync_playwright() as pw:
    engine = getattr(pw, os.getenv("UI_STREAM_BROWSER", "chromium"))
    options = {}
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if engine.name == "chromium" and chrome.exists():
      options["executable_path"] = str(chrome)
    instance = engine.launch(**options)
    yield instance
    instance.close()


STREAM_FPS = 30


@pytest.fixture(scope="module")
def jpeg(browser):
  page = browser.new_page(viewport={"width": 2160, "height": 1080})
  page.set_content(f'<body style="margin:0">{SVG.decode()}</body>')
  frame = page.screenshot(type="jpeg", quality=70)
  page.close()
  return frame


@pytest.fixture(scope="module")
def viewer_site(jpeg):
  # burst: deliver frames in pairs, the way congested Wi-Fi bunches them.
  counts = {"stream": 0, "input": [], "control_allowed": True, "burst": False}
  stream_port = 0

  class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
      pass

    def do_POST(self):
      if urlsplit(self.path).path == "/input":
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        counts["input"].append({"header": self.headers.get("X-UI-Stream-Control"), "gesture": body["gesture"],
                                "events": body["events"]})
        self.respond({"ok": True, "error": ""})
        return
      self.respond({"streamState": "running", "streamSequence": 1})

    def respond(self, body, mime="application/json"):
      if isinstance(body, dict):
        body = json.dumps(body).encode()
      self.send_response(200)
      self.send_header("Content-Type", mime)
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)

    def stream(self, mime):
      self.send_response(200)
      self.send_header("Content-Type", mime)
      self.end_headers()
      start = time.monotonic()
      try:
        for seq in range(1, STREAM_FPS * 20):
          captured = start + seq / STREAM_FPS
          sent = start + (seq + seq % 2) / STREAM_FPS if counts["burst"] else captured
          time.sleep(max(0.0, sent - time.monotonic()))
          header = b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\nX-Frame-Seq: %d\r\nX-Capture-Ms: %.1f\r\n\r\n"
          self.wfile.write(header % (len(jpeg), seq, captured * 1000) + jpeg + b"\r\n")
      except OSError:
        pass

    def do_GET(self):
      path = urlsplit(self.path).path
      if path == "/fixture":
        self.respond(b'''<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="/starpilot/system/the_galaxy/assets/mobile/css/material.css">
<style>body{margin:0}.fixture-shell{padding:16px;contain:layout style;transform:translateZ(0)}</style>
<script type="importmap">{"imports":{"vue":"/starpilot/system/the_galaxy/assets/vendor/vue/vue.esm-browser.js"}}</script>
<div id="root" class="fixture-shell"></div><script type="module">
import {createApp} from '/starpilot/system/the_galaxy/assets/vendor/vue/vue.esm-browser.js';
import {UiStream} from '/starpilot/system/the_galaxy/assets/mobile/js/views/UiStream.js';
window.testApp=createApp(UiStream);window.testApp.mount('#root');
</script>''', "text/html")
      elif path == "/api/device/status":
        self.respond({"streamPort": stream_port, "streamState": "running", "streamSequence": 1})
      elif path == "/status":
        allowed = counts["control_allowed"]
        self.respond({"state": "ready", "frameSequence": 1, "frameAgeMs": 10, "outputWidth": 2160, "outputHeight": 1080,
                      "control": {"available": True, "allowed": allowed, "reason": "" if allowed else "the car is onroad"}})
      elif path == "/telemetry":
        self.respond({"schemaVersion": 1, "isMetric": False, "vEgo": 31.7, "setSpeed": 72,
                      "leadDist": 30, "brake": 0, "engaged": True, "driveState": "enabled",
                      "cpuTempC": 50, "cpuUsagePercent": 27, "memoryUsagePercent": 44,
                      "modelExecMs": 19, "frameDropPerc": 0})
      elif path in ("/stream", "/frames"):
        counts["stream"] += 1
        self.stream("multipart/x-mixed-replace; boundary=frame" if path == "/stream" else "application/octet-stream")
      else:
        target = ROOT / ("system/ui/lib/ui_stream.html" if path == "/" else path.lstrip("/"))
        if not target.resolve().is_relative_to(ROOT) or not target.is_file():
          self.send_error(404)
          return
        mime = {".js": "text/javascript", ".css": "text/css", ".html": "text/html"}.get(target.suffix, "application/octet-stream")
        self.respond(target.read_bytes(), mime)

  servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
  stream_port = servers[1].server_port
  threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in servers]
  for thread in threads:
    thread.start()
  yield f"http://127.0.0.1:{servers[0].server_port}/fixture", counts
  for server, thread in zip(servers, threads, strict=True):
    server.shutdown()
    server.server_close()
    thread.join(2)


# Frame size for either display element: the player's canvas or the <img>.
FRAME_SIZE = "const nw = el.naturalWidth || el.width, nh = el.naturalHeight || el.height;"


def open_viewer(browser, viewer_site, width, height, fullscreen=None, player=True):
  page = browser.new_page(viewport={"width": width, "height": height})
  page.set_default_timeout(5000)
  page.on("pageerror", lambda error: print(error))
  if not player:
    page.add_init_script("delete window.createImageBitmap")
  if fullscreen:
    request = "undefined" if fullscreen == "missing" else "() => Promise.reject(new Error('denied'))"
    page.add_init_script(f'''Object.defineProperty(Element.prototype, 'requestFullscreen', {{configurable:true,value:{request}}});
Object.defineProperty(Element.prototype, 'webkitRequestFullscreen', {{configurable:true,value:undefined}});''')
  page.goto(viewer_site[0])
  page.locator("iframe").wait_for()
  frame = page.frame_locator("iframe")
  frame.locator("#cam[data-live]").wait_for()
  return page, frame


@pytest.mark.parametrize("size", [(390, 844), (844, 390), (768, 1024), (568, 320), (1280, 800)])
def test_telemetry_preserves_portrait_image_and_uses_landscape_sides(browser, viewer_site, size):
  page, frame = open_viewer(browser, viewer_site, *size)
  try:
    visible_width = f"el => {{ {FRAME_SIZE} return Math.min(el.clientWidth, el.clientHeight * nw / nh); }}"
    before = frame.locator("#cam").evaluate(visible_width)
    frame.locator("#telemetry-toggle").click()
    frame.locator("#telemetry-driving").get_by_text("enabled", exact=True).wait_for()
    stage = frame.locator("#stage").bounding_box()
    left = frame.locator("#telemetry-device").bounding_box()
    right = frame.locator("#telemetry-driving").bounding_box()
    if frame.locator("body").evaluate("() => innerWidth <= innerHeight"):
      assert frame.locator("#cam").evaluate(visible_width) >= before * 0.90
      # Device bar sits above the image and driving tiles below; neither overlaps it.
      assert left["y"] + left["height"] <= stage["y"] + 1
      assert right["y"] >= stage["y"] + stage["height"] - 1
    else:
      assert left["x"] + left["width"] <= stage["x"]
      assert stage["x"] + stage["width"] <= right["x"]
    assert frame.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
  finally:
    page.close()


@pytest.mark.parametrize("fullscreen", ["missing", "rejected"])
def test_fullscreen_fallback_preserves_stream_and_exits(browser, viewer_site, fullscreen):
  page, frame = open_viewer(browser, viewer_site, 390, 844, fullscreen)
  try:
    frame.locator("body").evaluate("() => { window.streamIdentity = 123; }")
    frame.locator("#fs").click()
    page.locator("dialog:modal").wait_for()
    assert page.locator("iframe").bounding_box() == {"x": 0, "y": 0, "width": 390, "height": 844}
    assert frame.locator("body").evaluate("() => window.streamIdentity") == 123
    frame.get_by_role("button", name="Exit expanded view").click()
    page.locator("dialog:modal").wait_for(state="hidden")
    assert page.locator("body").evaluate("el => el.style.overflow") == ""
    frame.locator("#fs").click()
    page.locator("dialog:modal").wait_for()
    page.keyboard.press("Escape")
    page.locator("dialog:modal").wait_for(state="hidden")
    frame.locator("#fs").click()
    page.locator("dialog:modal").wait_for()
    page.evaluate("window.testApp.unmount()")
    assert page.locator("dialog").count() == 0
    assert page.locator("body").evaluate("el => el.style.overflow") == ""
  finally:
    page.close()


def test_fullscreen_uses_native_api_when_available_and_rejects_spoofed_messages(browser, viewer_site):
  page, frame = open_viewer(browser, viewer_site, 844, 390)
  try:
    # A source tag alone cannot expand Galaxy: require the actual iframe window.
    page.evaluate('''() => window.postMessage({source:'starpilot-ui-stream',type:'fullscreen',expanded:true}, location.origin)''')
    assert page.locator("dialog:modal").count() == 0
    frame.locator("#fs").click()
    frame.get_by_role("button", name="Exit expanded view").wait_for()
    assert frame.locator("body").evaluate('''() => !!(document.fullscreenElement || document.webkitFullscreenElement) ||
      document.documentElement.classList.contains('expanded')''')
    frame.get_by_role("button", name="Exit expanded view").click()
    frame.get_by_role("button", name="Fullscreen", exact=True).wait_for()
  finally:
    page.close()


def _image_content(page, frame):
  content = frame.locator("#cam").evaluate(f"""el => {{
    {FRAME_SIZE}
    const r = el.getBoundingClientRect(), s = Math.min(r.width / nw, r.height / nh);
    const w = nw * s, h = nh * s;
    return {{left: r.left + (r.width - w) / 2, top: r.top + (r.height - h) / 2, width: w, height: h}};
  }}""")
  frame_box = page.locator("iframe").bounding_box()
  content["left"] += frame_box["x"]
  content["top"] += frame_box["y"]
  return content


def _events(counts):
  return [event for batch in counts["input"] for event in batch["events"]]


def _wait_for(page, counts, kind):
  deadline = time.monotonic() + 3.0
  while time.monotonic() < deadline and not any(e["type"] == kind for e in _events(counts)):
    page.wait_for_timeout(20)


@pytest.mark.parametrize("player", [True, False], ids=["player", "img"])
@pytest.mark.parametrize("size", [(390, 844), (1280, 800)])
def test_control_forwards_live_and_maps_through_the_letterbox(browser, viewer_site, size, player):
  counts = viewer_site[1]
  counts["input"].clear()
  page, frame = open_viewer(browser, viewer_site, *size, player=player)
  try:
    cam = frame.locator("#cam")
    # Off by default: a tap on the image sends nothing.
    box = cam.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    toggle = frame.locator("#control-toggle")
    toggle.wait_for()
    assert counts["input"] == []

    toggle.click()
    assert toggle.get_attribute("aria-pressed") == "true"
    content = _image_content(page, frame)
    x = content["left"] + content["width"] * 0.25
    y = content["top"] + content["height"] * 0.75
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + content["width"] * 0.25, y, steps=4)
    _wait_for(page, counts, "move")
    # Live: the press and the drag reach the comma while the finger is down.
    kinds = [e["type"] for e in _events(counts)]
    assert kinds[0] == "down" and "move" in kinds and "up" not in kinds
    page.wait_for_timeout(350)  # hold still: keepalives keep the press alive
    held = len(_events(counts))
    page.mouse.up()
    _wait_for(page, counts, "up")

    events = _events(counts)
    assert held > len(kinds)
    assert all(batch["header"] == "1" for batch in counts["input"])
    assert len({batch["gesture"] for batch in counts["input"]}) == 1
    assert events[0]["x"] == pytest.approx(0.25, abs=0.01) and events[0]["y"] == pytest.approx(0.75, abs=0.01)
    assert events[-1]["type"] == "up" and events[-1]["x"] == pytest.approx(0.5, abs=0.01)
    assert {e["type"] for e in events[1:-1]} <= {"move"}
    assert frame.locator("body").evaluate("el => el.scrollWidth <= innerWidth")
  finally:
    page.close()


def test_control_lost_pointer_cancels_instead_of_releasing(browser, viewer_site):
  counts = viewer_site[1]
  counts["input"].clear()
  page, frame = open_viewer(browser, viewer_site, 844, 390)
  try:
    frame.locator("#control-toggle").click()
    # Mouse pointer ids differ by browser (1 in Chrome, 0 in Firefox).
    frame.locator("#cam").evaluate("el => el.addEventListener('pointerdown', e => { window.downPointerId = e.pointerId; })")
    content = _image_content(page, frame)
    page.mouse.move(content["left"] + content["width"] / 2, content["top"] + content["height"] / 2)
    page.mouse.down()
    _wait_for(page, counts, "down")
    pointer_id = frame.locator("body").evaluate("() => window.downPointerId")
    # The browser takes the pointer away (scroll takeover, lost capture, ...).
    frame.locator("#cam").dispatch_event("pointercancel", {"pointerId": pointer_id, "bubbles": True})
    _wait_for(page, counts, "cancel")
    page.mouse.up()
    page.wait_for_timeout(200)
    kinds = [e["type"] for e in _events(counts)]
    assert kinds[-1] == "cancel" and "up" not in kinds
  finally:
    page.close()


def test_control_disables_itself_when_the_comma_refuses(browser, viewer_site):
  counts = viewer_site[1]
  page, frame = open_viewer(browser, viewer_site, 844, 390)
  try:
    toggle = frame.locator("#control-toggle")
    toggle.click()
    counts["control_allowed"] = False
    frame.locator("#control-toggle[disabled]").wait_for()
    assert toggle.get_attribute("aria-pressed") == "false"
    assert "onroad" in toggle.get_attribute("title")
  finally:
    counts["control_allowed"] = True
    page.close()


def test_player_paces_bunched_frames_evenly(browser, viewer_site):
  counts = viewer_site[1]
  counts["burst"] = True
  page, frame = open_viewer(browser, viewer_site, 844, 390)
  try:
    assert frame.locator("#cam").evaluate("el => el.tagName") == "CANVAS"
    page.wait_for_timeout(3000)
    stats = frame.locator("body").evaluate("() => window.uiStreamStats()")
    # Frames land in pairs every 66 ms. Shown as they land, every other one
    # would be superseded within the same refresh; paced, each gets its turn.
    intervals = sorted(stats["intervals"][-45:])
    assert len(intervals) >= 30
    median = intervals[len(intervals) // 2]
    assert 1000 / STREAM_FPS * 0.75 <= median <= 1000 / STREAM_FPS * 1.35
    assert sum(i > 1000 / STREAM_FPS * 1.75 for i in intervals) <= len(intervals) * 0.15
    assert 0 < stats["delayMs"] <= 100
  finally:
    counts["burst"] = False
    page.close()


def test_player_adds_no_delay_on_a_steady_link(browser, viewer_site):
  page, frame = open_viewer(browser, viewer_site, 844, 390)
  try:
    page.wait_for_timeout(2000)
    stats = frame.locator("body").evaluate("() => window.uiStreamStats()")
    assert stats["presented"] >= STREAM_FPS
    assert stats["delayMs"] < 25
    # Evenly spaced: without phase locking, due times that sit on a refresh
    # boundary alternate 1- and 3-refresh gaps.
    intervals = stats["intervals"][-45:]
    frame_ms = 1000 / STREAM_FPS
    assert sum(not frame_ms * 0.6 <= i <= frame_ms * 1.4 for i in intervals) <= len(intervals) * 0.15
  finally:
    page.close()


def test_viewer_falls_back_to_img_without_image_bitmaps(browser, viewer_site):
  page, frame = open_viewer(browser, viewer_site, 844, 390, player=False)
  try:
    assert frame.locator("#cam").evaluate("el => el.tagName") == "IMG"
    assert frame.locator("body").evaluate("() => typeof window.uiStreamStats") == "undefined"
  finally:
    page.close()
