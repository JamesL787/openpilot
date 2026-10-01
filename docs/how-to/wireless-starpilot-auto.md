# Wired and wireless Starpilot Auto

The comma presents itself to the car as an Android phone and projects wireless
Starpilot Auto onto the car's screen. The car shows either a car-sized StarPilot
UI (with touch) or a mirror of the comma's own screen. Nothing here touches
vehicle control.

**Status:** working on a 2026 Honda Civic (Alps Alpine `8A501-T20-A1` head unit,
Starpilot Auto protocol 4.1). The car negotiates 1280×720; the comma streams
hardware H.264 at 27–30 fps with about 70 ms frame age (p95). Other cars are
untested.

## Requirements

- A car whose head unit supports **wireless** Starpilot Auto. (A wired USB mode exists but is
  experimental and untested in a car; see step 3.)
- A comma 3X/four with Bluetooth enabled (`starpilot_autod` runs whenever Bluetooth is on).
- The **Starpilot Auto** app as an XAPK, APK or APKM file, downloaded in a phone or
  computer browser from an APK mirror. `17.6.663454-release` is known to work.
  Make sure you get the app itself; some mirrors' big download buttons hand you
  their own store installer instead.

## Quick setup

1. Enable **Starpilot Auto** and **Bluetooth** on the comma. Install the certificate
   in **Galaxy → Toggles → Starpilot Auto → Starpilot Auto Certificate**.
2. Open **Settings → Bluetooth → Starpilot Auto** on the comma, or
   **Galaxy → Toggles → Starpilot Auto → Connection**, and choose the link:
   - **Wireless:** pair the car once while parked/offroad, confirm both codes and
     allow Starpilot Auto on the car. Choose the car if it was not selected automatically.
     Keep Wi-Fi enabled; the comma obtains the car's network details itself.
   - **USB:** connect the comma to the car's Starpilot Auto **data** port with a short,
     data-capable cable. No pairing is required. A charging port alone will not work.
3. Leave **auto-connect** on and restore **Settings → System → Auto** after setup.
   Wired startup remains tied to the comma going **onroad**. Wireless also starts
   when the selected car connects over Bluetooth. **Connect** allows a parked test;
   **Disconnect** pauses automatic starting until the next drive or a manual Connect.

**Setup Help** on the comma, car display and Galaxy explains these steps for the
selected connection. **Last Error** includes a next action. Most temporary
interruptions retry automatically; repeated failures can be exported from Galaxy's
Starpilot Auto diagnostics. Bluetooth audio support alone does not imply wireless
Starpilot Auto.

## 1. Install the phone identity

The car only accepts a phone that presents Google's Starpilot Auto phone
certificate and its key. The comma installs them for you:

1. Open The Galaxy and go to **Toggles → Starpilot Auto → Starpilot Auto Certificate**.
2. Tap **Install recommended version**. The comma needs internet access.

Progress appears on the card. This takes a few seconds.

**Manual installation** remains available: expand it, tap **Install from File**,
and pick your APK, XAPK or APKM.

**Or have the comma download it from a link** accepts a direct link to the file,
e.g. in your own cloud storage.

The card shows the certificate's expiry date. Nothing needs restarting.

**Never commit or share the identity.** It is Google's key.

### Renewing

The 17.6.663454 certificate **expires 2026-12-23**. From 14 days before, The
Galaxy card and the device's Starpilot Auto status warn; after that Starpilot Auto
stops connecting. Download a newer Starpilot Auto version and use **Replace from
File** on the same card. The previous identity is kept in
`/data/starpilot_auto/identity.previous/`.

You can also use **Install recommended version** once the hosted recommendation
has been updated to a newer, tested version. Reinstalling the same version does
not extend its certificate's expiry date.

When you open the Starpilot Auto settings page with Starpilot Auto enabled, Galaxy
checks once for a newer recommended version in the background. An
**Update to Starpilot Auto certificate available** notice at the top of the page
offers **Update certificate**; updates are never installed automatically.

### On a computer instead

For testing with the Desktop Head Unit, or to install by hand, the same
install runs on a computer with Python and `cryptography`:

```bash
python tools/starpilot_auto/import_identity.py --apk ~/Downloads/starpilot-auto.xapk
# writes .cache/starpilot_auto/identity/ (git-ignored)
cd .cache/starpilot_auto/identity
COPYFILE_DISABLE=1 tar -cf - phone-cert.pem phone-key.pem root-cert.pem provenance.json | \
  ssh comma@<comma-ip> 'umask 077 && mkdir -p /data/starpilot_auto/identity && \
    tar -xf - -C /data/starpilot_auto/identity && chmod 700 /data/starpilot_auto /data/starpilot_auto/identity && \
    chmod 600 /data/starpilot_auto/identity/*'
```

`COPYFILE_DISABLE=1` stops macOS adding `._*` metadata files.

## 2. Pair the car

Bluetooth pairing and scanning only work while the comma is **offroad**, but
the car's screen only works with the car on, which normally puts the comma
onroad. Force it offroad while parked:

1. Car on, parked. On the comma: **Settings → System**, set to **Offroad**.
2. **Settings → Bluetooth → starpilot auto → pair a new car.**
3. On the car: Bluetooth / phone settings → add a new device. Select the car in the comma's list and confirm the code on both screens.

A car that advertises wireless Starpilot Auto and pairs during this window becomes
the Starpilot Auto car automatically. Otherwise use **starpilot auto → choose car**;
cars marked "(starpilot auto)" advertise wireless Starpilot Auto. Choosing a car also
marks it trusted, so the car's own connections are accepted while onroad.

Pairing is needed once per car. Set **Settings → System** back to **Auto** afterwards.

## 3. Projection starts on its own

With **auto-connect** on (the default), there is nothing to press. Projection
starts when the car is on:

- the comma goes onroad (ignition), or
- the car connects to the comma over Bluetooth, as it does with a phone when it
  powers on. The comma keeps a hands-free gateway registered for this, and it
  answers only the chosen car.

Bluetooth must be up first; auto-connect waits for the adapter instead of
spending retries while the radio starts after boot. It ends the session once the
car has been gone (offroad and no Bluetooth link) for 60 s, which also puts the
comma's previous Wi-Fi back.

The comma connects over Bluetooth, the car sends its Wi-Fi hotspot details, the
comma joins that hotspot (it leaves any other Wi-Fi; cellular stays up), and
projection starts over TCP. The status line reads
`projecting / car layout / <fps> fps` once video is flowing. The service retries
on its own with backoff while the car is present.

The comma presents itself as a phone (smartphone Class of Device) only while
pairing and while connecting; it switches back as soon as the car has sent its
Wi-Fi details, so controllers and other Bluetooth devices see a normal comma
during the drive.

**stop** ends projection and holds auto-connect off until the next drive (the
next time the comma goes onroad). **start** starts it by hand at any time.

In **Settings → Bluetooth → starpilot auto**:

- **turn off auto-connect / turn on auto-connect** switches automatic starting. With it off, use **start**; the status reads `off / <car>` instead of `auto / <car>`.

- **mirror comma screen / use car layout** switches what the car shows, from the next session.
- **show last error** shows why the last attempt failed.
- **use wired (usb) / use wireless** (while stopped) switches to projecting over a USB cable from the
  car to the comma's USB-C port, with no pairing or Wi-Fi. Experimental: not yet tested in a car.

**Touch.** In the car layout, offroad touches control the StarPilot UI. Onroad,
the driving view and map ignore touches; the dedicated quick menu and the
Home/Navigate screens it opens handle their own input and navigation speed
restrictions. The driving view therefore omits the unused radial favorites menu
and its corner arrow, avoiding per-frame layout, settings reads and drawing.
C3X's own display keeps its cached corner hint and radial favorites; C4's
separate favorites overlay is unchanged. Navigation destination favorites are
unaffected. Mirror view has no touch and still shows the device's own UI.

**C4 screen sleep.** In The Galaxy → Starpilot Auto → Layout (or the car's
Settings → Car Display), **Turn Off Comma Display** is on by default. Onroad, the
comma four display and native drawing sleep after the existing screen timeout
while fresh car-view frames are being sent. Starpilot Auto's camera, path, HUD and map settings
are unchanged. Tap the comma once to wake it for another timeout period. Lost
focus or video stalled for over 3 s, disconnect/fallback, disabling the toggle, and
critical alerts (Take Control) always wake it and hold it awake while shown.
**Wake Comma Display For** chooses what else does: warning alerts (Pay Attention,
faults; the default), informational alerts, engagement, disengagement, turn signals,
and steering wheel or Bluetooth buttons. Alerts hold it awake while shown; the other
events wake it for one timeout. Standby wake choices do not apply. Turning the setting
off asks first: two screens drawing at once uses additional CPU. Settings saved before
the wake choices existed stored the old default, so they start asleep. C3X and mirror mode are unchanged. A native Live UI viewer
keeps native drawing active even with the physical panel off. The setting lives
in `car_screen.json`; it can be configured without a connected car.

## Configuration

`/data/starpilot_auto/config.json`, written when you choose a car. Edit with the
service stopped, then restart `starpilot_autod` to reload the file.

| Key | Default | Meaning |
|---|---|---|
| `connection` | `"wireless"` | `"wireless"`: Bluetooth + the car's Wi-Fi; `"wired"`: USB (experimental) |
| `usb_mode` | `"auto"` | Wired: try AOA handshake, then direct accessory presentation if the connected host sends no START; `"handshake"` or `"direct"` forces one path. |
| `view` | `"car"` | `"car"`: car-sized StarPilot UI; `"mirror"`: copy of the comma screen |
| `encoder` | `"auto"` | `"auto"`: hardware H.264, falling back to libx264; `"hardware"` / `"software"` to force |
| `fps` | `0` | `0` = automatic (30 hardware, 15 software); otherwise a cap, 5–30 |
| `bitrate_kbps` | `6000` | 1000–12000 |
| `rate_control` | `"cbr"` | hardware encoder: `"cbr"` holds the bitrate steady; `"vbr"` lets it vary with the picture, as before |
| `gpu_nv12` | `true` | car layout: convert to the encoder's NV12 on the GPU, so a third of the RGBA data is read back and the encoder does no conversion |
| `async_readback` | `true` | car layout: read each frame back without stalling the renderer on the GPU (published one update step later) |
| `render_profile` | `true` | car layout: keep the always-on sampling profile in `logs/render_profile.txt` |
| `render_profile_kb` | `256` | size of each `render_profile` file before it rotates (16–4096) |
| `verify_head_unit` | `true` | verify the car's certificate against `root-cert.pem` |
| `auto_connect` | `true` | start projection when the chosen car is on; stop once it has been gone for 60 s |
| `rfcomm_channel` | `0` | `0` = discover over SDP; set only to work around a broken SDP record |
| `rfcomm_cache` | `{}` | channel learned over SDP per car, used next time to skip discovery; dropped when the car does not answer on it |
| `phone_class` | `true` | present as a phone while pairing/connecting (smartphone Class of Device) and keep the car's hands-free gateway |
| `wifi_interface` | `"wlan0"` | interface used to join the car's hotspot |
| `device_name` | `"StarPilot"` | name shown to the car |

## Logs

Everything is under `/data/starpilot_auto/logs/` on the comma:

- `session-YYYYMMDD-HHMMSS.jsonl`: one file per **start**, covering every retry until **stop**. One JSON object per line, UTC timestamps. The newest 20 are kept.
- `car_ui.log`: output of the car-layout renderer, rewritten each time the renderer starts (startup, crashes, and `render_stats` every 10 seconds while drawing).
- `render_profile.txt` / `render_profile.1.txt`: where the renderer's time goes, one entry per minute of projection (below).

`render_stats` reports produced FPS and average per-frame wall times in
milliseconds: `update_ms` (UI state and touch routing), `map_ms` (map tiles),
`layout_ms` (drawing the layout), `map_draw_ms`, `menu_ms`, `compose_ms` (ending the
UI pass and, for RGBA fallback, placing the picture in the car's frame), `cache_ms`,
`convert_ms` (GPU NV12 passes, including padding and flipping), `readback_ms`, `readback_wait_ms` (waiting for the GPU to finish the
frame), `publish_ms` (copying it to starpilot_autod), and `frame_ms` for the whole
frame. `draw_ms` is the sum of the drawing sections, comparable with older logs.
`cpu_ms` is the renderer's own CPU time: `frame_ms` well above `cpu_ms` means it was
waiting for a CPU core or the GPU driver rather than working. The renderer runs on
core 6 at `SCHED_IDLE`, so camerad, which shares that core without realtime
priority, always runs first. Startup logs a `cpu_placement` line with the policy and the
cores it inherited. Later lines report when the pin to core 6 is applied again,
for example after offroad power saving took the big cores offline
(`starpilot/system/starpilot_auto/placement.py` explains the choice).
The `pipeline` line at startup says whether frames are NV12 or RGBA and read back
asynchronously. The car renderer uses single-sample rendering (`msaa: 0`) to reduce
GPU and memory traffic shared with driver monitoring. This makes polygon edges
less smooth but preserves the negotiated resolution and configured frame rate.
With NV12, `fused_compose: true` means margins and the vertical flip are handled
inside conversion; there is no second full-size RGBA target or composition pass.
RGBA fallback retains that pass for encoder compatibility.
Compare these with the session's sent `fps`, `encode_ms`,
`frame_age_p95_ms`, and receiver `pending` count to distinguish rendering delays
from encoding or delivery delays.

`render_profile.txt` (next to the session logs) shows where the car renderer's
time goes, drive after drive, with nothing to start: a sampler looks at the
renderer 25 times a second and every minute appends the busiest functions and
lines, whether that minute was onroad, and its `render_stats`. When the file
reaches `render_profile_kb` it becomes `render_profile.1.txt` (replacing the older
one) and a new file starts. Read the "on the stack" section: the innermost-function
and line sections credit pure-Python work to the next raylib/GL call. It costs the
renderer about 0.5 ms per frame; set `render_profile` to `false` to turn it off.
When a sample catches a Params read, the report also lists the key name (never
its value). These percentages are sampled waits, not counts of all reads. See
[profile-guided optimizations and device measurements](starpilot-auto-render-performance.md).
`gpu_ms` is disabled during normal rendering (`gpu_timing: false`, `gpu_ms: 0`).
For a diagnostic run only, set `STARPILOT_AUTO_GPU_TIMING=1` in the renderer's environment to
measure how long the GPU still had to go after the CPU finished one frame in 30.
This uses a blocking `glFinish`, so it changes the workload being measured.

Without a car, `tools/starpilot_auto/car_view_probe.py` renders the car layout on the
comma and reports its frame rate and encode time (`--rgba --sync-readback
--rate-control vbr` for the previous pipeline), and `tools/starpilot_auto/nv12_check.py`
checks the GPU NV12 conversion against the CPU one. The Bluetooth
panel shows sent FPS over five seconds, including startup time in that window.
While the car shows its own screen, frame production pauses and the renderer stays
loaded until the session ends.

For the fused conversion's pixel regression checks (no car or settings changes):

```bash
STARPILOT_AUTO_GL_TEST=1 python -m pytest -q -o addopts= --confcutdir=starpilot/system/starpilot_auto/tests starpilot/system/starpilot_auto/tests/test_gpu_nv12.py
```

These tests compare real GPU output with the original RGBA composition followed
by CPU NV12 conversion, including odd margins, chroma at the padding boundary,
and both readback modes. They support the comma's EGL context and macOS CGL.
Pixel correctness on a desktop does not establish comma performance: after
installing a renderer change, compare sent FPS and frame age with the same car
settings, and check that `driverStateV2` and `driverMonitoringState` sustain 20 Hz
under the same onroad workload. Do not relax the communication checks to make a
slow model appear healthy. The model's `gpuExecutionTime` is elapsed wall time
around its warp/inference/readback, not a hardware-only GPU measurement.

Readable timeline of the latest session, without the hands-free chatter:

```bash
ssh comma@<comma-ip> 'cat $(ls -t /data/starpilot_auto/logs/session-*.jsonl | head -1)' | python3 -c '
import json, sys
for line in sys.stdin:
    r = json.loads(line); t = r.pop("t")[11:19]; e = r.pop("event")
    if not e.startswith("hfp"):
        print(t, e, json.dumps(r)[:240])'
```

Events worth knowing:

| Event | Meaning |
|---|---|
| `session_start` | `trigger`: `manual`, `onroad` or `car_connected` |
| `stage` | progress: `connecting_bluetooth` → `discovering` → `rfcomm` → `wifi_start` → `connecting_tcp` → `authenticating` → `negotiating` → `streaming` |
| `rfcomm_channel` | channel used and its `source`: `sdp`, `cache` or `config` |
| `auto_connect_stop` | auto-connect ended the session because the car was gone |
| `bootstrap_version` | car make/model/head unit and its wireless protocol version |
| `bootstrap_credentials` / `wifi_joined` | car hotspot SSID and the comma's address on it (the key is never logged) |
| `version` | projection protocol the car asked for and the comma's reply (e.g. `4.1` → `6.1`) |
| `head_unit_verified` | the car's certificate subject |
| `video_setup` | negotiated resolution and frame rate |
| `video_focus` | `focus 1` = car shows projection, `focus 2` = car shows its own screen |
| `stats` | every 30 s: fps, frames sent/acked, encode time, frame age, touch events |
| `attempt_failed` | why an attempt failed and at which stage; a retry follows |
| `session_ended` | the car ended projection |

The service's live status (the same data the settings menu shows):

```bash
ssh comma@<comma-ip> 'cd /data/openpilot && PYTHONPATH=/data/openpilot /usr/local/venv/bin/python -c "
from openpilot.starpilot.system.starpilot_auto.protocol import StarpilotAutoClient
import json; print(json.dumps(StarpilotAutoClient().status(), indent=2, default=str))"'
```

After editing Starpilot Auto code on the comma, restart the service; the manager starts it again:

```bash
ssh comma@<comma-ip> 'pkill -TERM -f "^starpilot.system.starpilot_auto.daemon$"'
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| **pair a new car** missing, **scan for devices** does nothing | The comma is onroad. Use the **Offroad** switch (step 2). |
| Projection does not start by itself | Status `paused until next drive`: **stop** was pressed; it resumes next drive, or press **start**. Status `stopped / error` with `auto-connect: …`: see **show last error** (often the identity). Otherwise check that auto-connect is on and a car is chosen. |
| Car-screen touches do nothing | The comma is onroad (maybe forced **Onroad**). Set Settings → System to **Auto**. |
| `Starpilot Auto identity missing` / `expired` / `is unusable` | Install or renew it in The Galaxy → Vehicle Controls → Starpilot Auto Identity (step 1). |
| The Galaxy says *This file is not the Starpilot Auto app* | The file is not the Starpilot Auto app (often a mirror's store installer). Download the app itself. |
| The Galaxy says *This Starpilot Auto version is not supported* | That app version is not supported yet; use 17.6.663454 or another version that works. |
| `waiting for car: wifi_start: head unit did not answer` | The car did not start Wi-Fi. The comma asks it to after 5 s; occasional misses retry on their own. If it never succeeds, delete the comma on the car and pair again: the car can remember an earlier failure. |
| Car says the device is not compatible / connect a phone with the latest OS | The comma dropped the connection during setup. Check `attempt_failed` in the log. |
| Car shows Starpilot Auto briefly, then its own screen | Look at `video_focus`: repeated `focus 1` then `focus 2` about 3 s later means the car is not getting decodable video. |
| `projecting: timed out` or `Video acknowledgement older than 1.5 s` | The Wi-Fi link to the car stalled. The service reconnects automatically. |
| Status shows `mirror (car view failed: …)` | The car layout failed to start and the view fell back to mirror; see `car_ui.log`. |
| `hfp_closed … Connection reset by peer` about every second | The car keeps dropping the hands-free link. Known; it has not blocked projection. |

## Testing without the car

Google's **Desktop Head Unit** shows the comma's projection on a computer, no car
needed: see [starpilot-auto-desktop-head-unit.md](starpilot-auto-desktop-head-unit.md).
It does not test Bluetooth pairing, the Wi-Fi handoff or car-specific behavior.

## Known limitations

- Video and touch only: no audio, microphone, calls or navigation data are projected.
- In the car, sessions so far have lasted about a minute before a reconnect (the service reconnects
  on its own); with the Desktop Head Unit they run for 15+ minutes.
- Tested on one car (2026 Honda Civic).
- The identity comes from the Starpilot Auto app and expires with it; renew it from a newer app version in The Galaxy.


## Vehicle and DIY dongle compatibility

For a DIY wireless adapter plugged into a car that already supports wired Starpilot Auto, choose **Wireless** on
the comma and pair/select the adapter. The adapter manages its own USB link to
the car. A successful manual connection does not establish cold-boot or ignition
reconnect compatibility; test both.

Simple legacy dongles receive the original bootstrap sequence without extra
phone pings during Wi-Fi join. Receivers that negotiate a version or send pings
retain join keepalives. Silent peers receive one start prompt after 2.5 seconds;
setup has bounded deadlines even if the peer sends pings continuously.
Invalid/placeholder BSSIDs are ignored, and valid BSSIDs retain the SSID fallback.
Wired enumeration now includes a 500 ms detach interval before rebinding.

### Reconnect behavior and validation

Retries start at 2 seconds, increase to 4, 8, 15 and 30 seconds, and reset after
30 seconds of projection. A slow failed setup does not reset the backoff. The
status displays the remaining wait. The existing onroad/car-presence policy and
manual-disconnect hold are unchanged.

Wireless setup cancels and joins its Wi-Fi worker before releasing the network
or starting another attempt. Stopping during backoff restores the previous
Wi-Fi unless the user chose another network. Projection profiles use a consistent
hardware MAC address and disable Wi-Fi power saving only for that profile.
Pings alone cannot suppress the start prompt, and credentials are accepted
before or after the projection endpoint. A secured network missing its password
reports an error instead of being treated as an open network.

Wired setup checks the controller state as well as uevents. After switching to
accessory mode it waits up to 15 seconds for configuration; it does not start
blocking accessory I/O against an unconfigured device. Cleanup detaches the
controller, waits for the bridge workers, then restores the previous gadget.

Automated coverage includes reordered bootstrap messages, strict legacy dongles,
fragmentation, old TLS cipher offers, multiple displays, interrupted Wi-Fi joins,
stop during backoff, missing/stale USB events, and simulated wired projection.
These checks do **not** establish compatibility with additional physical cars.
For each receiver, record make/model/year and firmware and test:

- Cold boot with the car already on, then a normal offroad-to-onroad transition.
- Wireless: previously paired reconnect, delayed hotspot startup, and a temporary
  Wi-Fi interruption without removing the pairing.
- Wired: cable attached before boot, unplug/replug during the drive, and a car
  that keeps the USB port powered after switching off.
- Disconnect/Connect, the next drive, returning from the car's own screen, and
  at least 30 minutes of continuous projection. Export logs for each failure.

### Protocol references

- [Android Open Accessory](https://source.android.com/docs/core/interaction/accessories/aoa):
  host/device roles, START and re-enumeration, accessory interface and configuration.
- [Android accessory gadget driver](https://android.googlesource.com/kernel/common/+/6be064d42c55/drivers/usb/gadget/function/f_accessory.c):
  blocking reads and disconnect handling; [Linux close semantics](https://man7.org/linux/man-pages/man2/close.2.html)
  explain why closing a descriptor from another thread is insufficient.
- [aa-proxy-rs Bluetooth implementation](https://github.com/aa-proxy/aa-proxy-rs/blob/main/src/bluetooth.rs):
  receiver interoperability reference for SDP and wireless bootstrap; this is not
  an official Starpilot Auto specification.
- [NetworkManager Wi-Fi settings](https://www.networkmanager.dev/docs/api/latest/settings-802-11-wireless.html):
  D-Bus `assigned-mac-address`, `powersave` and BSSID behavior.
