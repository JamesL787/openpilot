"""Step 3: a local page for labelling the V-ASM crops from extract_crops.py, one at a time.

  python3 tools/vasm_finetune/labeler.py --crops ~/oprad-scratch/vasm/crops
  then open http://127.0.0.1:8765/?split=test   (every test crop, labelled blind)
       or   http://127.0.0.1:8765/?split=train  (only the crops extract_crops flagged for review)
       or   http://127.0.0.1:8765/?split=review (only the crops in <crops>/review_list.json: owner labels an agent
                                                  disagreed with, shown with the agent's label; a key press re-labels)
       or   http://127.0.0.1:8765/?split=queue  (every crop of the segment sides in <crops>/queue.json, labelled blind:
                                                  dense validation segments, so the event-level gate has more to score)

Keys: 0 no car, 1 adjacent lane, 2 two or more lanes over, t truck part (labelled 1 and tagged so training can
oversample it), x unsure (left out of training and scoring), left/right arrows to move. Class rules: see the page legend.
Labels go to <crops>/labels.json after every key press, so closing the page loses nothing and reopening resumes at
the first unlabelled crop. Stdlib only, listens on 127.0.0.1.

Test crops are labelled blind: the page hides the model's probabilities and its proposal there, otherwise the
benchmark would lean toward the model it is meant to judge. Radar and the pass hold stay visible on both splits.
"""

import argparse
import csv
import datetime
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PAGE = r"""<!doctype html><meta charset="utf-8"><title>V-ASM labeler</title>
<style>
 body{font:14px system-ui;background:#111;color:#ddd;margin:16px}
 #row{display:flex;gap:12px;align-items:flex-start}
 img{image-rendering:auto;border:3px solid #333}
 #main{width:528px;height:528px}
 .ctx{width:176px;height:176px;opacity:.75}
 #info{white-space:pre;font-family:ui-monospace,monospace;font-size:13px}
 .done{border-color:#2a7} a{color:#8cf}
 b{color:#fff} .k{display:inline-block;border:1px solid #666;border-radius:4px;padding:0 6px;margin-right:4px}
</style>
<div><a href="?split=test">test</a> &middot; <a href="?split=train">train</a> &middot; <a href="?split=review">review</a> &middot; <a href="?split=queue">queue</a></div>
<div id="bar"></div>
<div id="row">
 <div><div>before</div><img class="ctx" id="prev2"><br><img class="ctx" id="prev1"></div>
 <div><img id="main"></div>
 <div><div>after</div><img class="ctx" id="next1"><br><img class="ctx" id="next2"></div>
 <div id="info"></div>
</div>
<p><span class="k">0</span>no car &nbsp; <span class="k">1</span>adjacent lane: the vehicle covers the lane line and fills most
 of the crop, or any part of an adjacent-lane vehicle is in view (a bit of its front, a truck hitch)
 &nbsp; <span class="k">2</span>two or more lanes over, judged by distance: the vehicle sits beyond the lane line
 (no lane lines, e.g. parking lots: small and far = 2, big and close = 1)
 &nbsp; <span class="k">t</span>truck part (trailer, container, rest of the cab): saved as 1, tagged for oversampling
 &nbsp; <span class="k">x</span>unsure &nbsp; <span class="k">&larr;</span><span class="k">&rarr;</span>move</p>
<p style="color:#888">"before" and "after" are this side 0.25 s and 0.5 s either side.</p>
<script>
const split = new URLSearchParams(location.search).get("split") || "test";
let rows = [], labels = {}, i = 0, reviewed = x => x.file in labels;
const NAMES = {0: "no car", 1: "adjacent", 2: "2+ lanes over", x: "unsure"};
async function load() {
  const r = await (await fetch("/api/rows?split=" + split)).json();
  rows = r.rows; labels = r.labels;
  // review: resume at the first crop not re-labelled since the review list was made
  const todo = split === "review" ? (x => !(x.file in labels) || (labels[x.file].at || "9") < r.created)
    : split === "queue" ? (x => !(x.file in labels) || "by" in labels[x.file])  // agent labels still need the owner's
    : (x => !(x.file in labels));
  reviewed = x => !todo(x);
  i = rows.findIndex(todo); if (i < 0) i = 0;
  show();
}
function img(id, file) {
  const el = document.getElementById(id);
  el.src = file ? "/crop/" + file : ""; el.style.visibility = file ? "visible" : "hidden";
}
function show() {
  const r = rows[i]; if (!r) { document.getElementById("bar").textContent = "nothing to label"; return; }
  const n = rows.filter(reviewed).length;
  document.getElementById("bar").innerHTML = `<b>${split}</b> ${i + 1}/${rows.length} &nbsp; ${split === "review" ? "reviewed" : "labelled"} ${n} &nbsp; ` +
    (r.file in labels ? `this one: <b>${NAMES[labels[r.file].label]}${labels[r.file].truck ? " (truck part)" : ""}</b>` : "unlabelled");
  const main = document.getElementById("main");
  main.src = "/crop/" + r.file; main.className = reviewed(r) ? "done" : "";
  img("prev2", r.prev2); img("prev1", r.prev1); img("next1", r.next1); img("next2", r.next2);
  let s = `${r.route} seg ${r.seg}  t=${r.t}\ncar side: ${r.car_side.toUpperCase()}  (image ${r.image_side})\n` +
    `speed ${r.v_ego} m/s  blinker ${r.blinker == 1 ? "ON" : "off"}\n\n` +
    `radar ${r.car_side}: ` + (r.radar_status == 1 ? `${r.radar_drel} m ahead, rel ${r.radar_vrel} m/s` : "none") +
    `\npass hold: ${r.pass_hold == 1 ? "HOLDING" : "-"}\n`;
  if (split !== "test" && split !== "queue") s += `\nmodel: nocar ${r.p_nocar}  car ${r.p_car}  distant ${r.p_distant}\n` +
    `proposal: ${NAMES[r.proposal]}\nflag: ${r.review || "-"}`;
  if (split === "review") s += `\n\nAGENT said: ${NAMES[r.agent_label]}\nyou said: ${NAMES[r.owner_label]}` +
    `\n(press the key for the right answer, even if it is yours)`;
  document.getElementById("info").textContent = s;
}
let saving = Promise.resolve(), failed = 0;
function setLabel(v, truck = false) {
  // label and advance immediately, so fast key presses each hit their own crop; saves go out in order
  const file = rows[i].file;
  labels[file] = truck ? {label: v, truck} : {label: v};
  saving = saving.then(() => fetch("/api/label", {method: "POST", body: JSON.stringify({file, label: v, truck})}))
    .then(r => { if (!r.ok) throw r; }).catch(() => { failed++; alert("Save failed for " + file + "; is labeler.py still running?"); });
  if (i < rows.length - 1) i++;
  show();
}
document.addEventListener("keydown", e => {
  if (e.key === "0" || e.key === "1" || e.key === "2") setLabel(Number(e.key));
  else if (e.key === "x") setLabel("x");
  else if (e.key === "t") setLabel(1, true);
  else if (e.key === "ArrowRight" && i < rows.length - 1) { i++; show(); }
  else if (e.key === "ArrowLeft" && i > 0) { i--; show(); }
});
load();
</script>"""


class Store:
  def __init__(self, crops):
    self.crops = os.path.abspath(crops)
    self.path = os.path.join(self.crops, "labels.json")
    self.lock = threading.Lock()
    self.labels = json.load(open(self.path)) if os.path.exists(self.path) else {}
    with open(os.path.join(self.crops, "manifest.csv")) as f:
      self.rows = list(csv.DictReader(f))
    # context neighbours: same segment and image side, by time
    by_track = {}
    for k, r in enumerate(self.rows):
      by_track.setdefault((r["route"], r["seg"], r["image_side"]), []).append(k)
    self.neighbours = {}
    for idx in by_track.values():
      idx.sort(key=lambda k: float(self.rows[k]["t"]))
      for p, k in enumerate(idx):
        self.neighbours[k] = {
          name: idx[p + off] if 0 <= p + off < len(idx) else None for name, off in (("prev2", -2), ("prev1", -1), ("next1", 1), ("next2", 2))
        }

  def view(self, split):
    out = []
    for k, r in enumerate(self.rows):
      if r["split"] == split and (split == "test" or r["review"]):
        row = dict(r)
        for name, other in self.neighbours[k].items():
          row[name] = self.rows[other]["file"] if other is not None else ""
        out.append(row)
    # one camera view at a time: segment, side, then time
    out.sort(key=lambda r: (r["route"], int(r["seg"]), r["image_side"], float(r["t"])))
    return out

  def review(self):
    # crops the owner labelled and an agent labelled differently; most useful first (class 1 vs 2 under the new rule)
    path = os.path.join(self.crops, "review_list.json")
    if not os.path.exists(path):
      return [], ""
    lst = json.load(open(path))
    out = []
    for k, r in enumerate(self.rows):
      item = lst["items"].get(r["file"])
      if item is not None:
        row = dict(r, agent_label=item["agent"], priority=item["priority"], owner_label=self.labels.get(r["file"], {}).get("label", ""))
        for name, other in self.neighbours[k].items():
          row[name] = self.rows[other]["file"] if other is not None else ""
        out.append(row)
    out.sort(key=lambda r: (r["priority"], r["route"], int(r["seg"]), r["image_side"], float(r["t"])))
    return out, lst["created"]

  def queue(self):
    # every crop of the queued (route, seg, side)s, in camera-view order; route matched by suffix like the notes use
    path = os.path.join(self.crops, "queue.json")
    if not os.path.exists(path):
      return []
    want = [(q["route"], str(q["seg"]), q["side"]) for q in json.load(open(path))["sides"]]
    out = []
    for k, r in enumerate(self.rows):
      if any(r["route"].endswith(rt) and r["seg"] == sg and r["image_side"] == sd for rt, sg, sd in want):
        row = dict(r)
        for name, other in self.neighbours[k].items():
          row[name] = self.rows[other]["file"] if other is not None else ""
        out.append(row)
    out.sort(key=lambda r: (r["route"], int(r["seg"]), r["image_side"], float(r["t"])))
    return out

  def set(self, file, label, truck=False):
    if label not in (0, 1, 2, "x") or (truck and label != 1) or not any(r["file"] == file for r in self.rows):
      return False
    with self.lock:
      self.labels[file] = {"label": label, "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}  # noqa: UP017 (macOS python3 is 3.9)
      if truck:
        self.labels[file]["truck"] = True
      tmp = self.path + ".tmp"
      with open(tmp, "w") as f:
        json.dump(self.labels, f, indent=0, sort_keys=True)
      os.replace(tmp, self.path)
    return True


def handler(store):
  class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
      pass

    def send(self, code, body, ctype):
      self.send_response(code)
      self.send_header("Content-Type", ctype)
      self.send_header("Content-Length", str(len(body)))
      self.end_headers()
      self.wfile.write(body)

    def do_GET(self):
      url = urlparse(self.path)
      if url.path == "/":
        return self.send(200, PAGE.encode(), "text/html; charset=utf-8")
      if url.path == "/favicon.ico":
        return self.send(204, b"", "image/x-icon")
      if url.path == "/api/rows":
        split = parse_qs(url.query).get("split", ["test"])[0]
        rows, created = store.review() if split == "review" else (store.queue() if split == "queue" else store.view(split), "")
        return self.send(200, json.dumps({"rows": rows, "labels": store.labels, "created": created}).encode(), "application/json")
      if url.path.startswith("/crop/"):
        path = os.path.normpath(os.path.join(store.crops, url.path[len("/crop/") :]))
        if path.startswith(store.crops + os.sep) and path.endswith(".png") and os.path.isfile(path):
          with open(path, "rb") as f:
            return self.send(200, f.read(), "image/png")
      return self.send(404, b"not found", "text/plain")

    def do_POST(self):
      if urlparse(self.path).path != "/api/label":
        return self.send(404, b"not found", "text/plain")
      body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
      ok = store.set(str(body.get("file", "")), body.get("label"), body.get("truck") is True)
      return self.send(200 if ok else 400, b"ok" if ok else b"bad label", "text/plain")

  return Handler


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--crops", default=os.path.expanduser("~/oprad-scratch/vasm/crops"))
  ap.add_argument("--port", type=int, default=8765)
  args = ap.parse_args()
  store = Store(args.crops)
  print(f"{len(store.rows)} crops, {len(store.labels)} labelled; open http://127.0.0.1:{args.port}/?split=test", flush=True)
  ThreadingHTTPServer(("127.0.0.1", args.port), handler(store)).serve_forever()


if __name__ == "__main__":
  main()
