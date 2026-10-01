# Test Starpilot Auto with the Desktop Head Unit

Google's **Desktop Head Unit (DHU)** is a car screen that runs on your computer.
With it you can see and use the comma's Starpilot Auto projection without a car:
the car-sized StarPilot UI (or a mirror of the comma's screen), touch, and the
hardware video encoder.

```
 comma (plays the phone)  ──SSH tunnel──▶  your computer: Desktop Head Unit window
 Starpilot Auto projection                    (the "car")
```

No Android phone, emulator or Starpilot Auto app install is involved: the comma
itself does what the phone app would. Nothing is opened on your network; the DHU
reaches the comma through SSH.

What the DHU does **not** test: Bluetooth pairing, the Wi-Fi handoff to the car,
and car-specific behavior. Real head units ask for other protocol versions and
screen sizes and can be stricter about the video stream. A DHU pass is a good
sign, not proof that a car will work. For using Starpilot Auto in a car, see
[wireless-starpilot-auto.md](wireless-starpilot-auto.md).

## You need

| What | Details |
|---|---|
| A computer | macOS or Linux (the launcher is a bash script). Windows is untested. |
| The DHU | Part of the Android SDK; see step 1. Android Studio is the easiest way to get it. |
| SSH access to the comma | Enable SSH and add your GitHub SSH key in the comma's settings; see [connect-to-comma.md](connect-to-comma.md). |
| A comma with Starpilot Auto | Software that includes `starpilot/system/starpilot_auto` and `tools/starpilot_auto/dhu_device.py`, with Bluetooth enabled (the Starpilot Auto service runs only then). |
| The Starpilot Auto identity on the comma | Install it once in The Galaxy: **Vehicle Controls → Starpilot Auto Identity**. The DHU, like a car, rejects anything but Google's phone certificate. See [wireless-starpilot-auto.md](wireless-starpilot-auto.md#1-install-the-phone-identity). |

The comma and the computer only need to reach each other over SSH (same network, a tether, or a VPN).

## 1. Install the Desktop Head Unit (once)

1. Open **Android Studio → Settings → Languages & Frameworks → Android SDK → SDK Tools**.
2. Tick **Starpilot Auto Desktop Head Unit Emulator** and apply.
   Command-line alternative: `sdkmanager "extras;google;auto"`.
3. It is installed in `<SDK>/extras/google/auto/`. The SDK is usually `~/Library/Android/sdk` on macOS
   and `~/Android/Sdk` on Linux; Android Studio shows the exact path on the same settings page.
4. Make it executable:

   ```bash
   chmod +x <SDK>/extras/google/auto/desktop-head-unit
   ```

   Keep the other files in that folder (such as `libusb`) next to it.

**Linux** also needs GLIBC 2.32+ (`ldd --version`) and `sudo apt-get install libc++1 libc++abi1`.

Check it starts: `cd <SDK>/extras/google/auto && ./desktop-head-unit --version`.

## 2. Set up SSH to the comma (once)

Give the comma a short name in `~/.ssh/config`, so every tool can use it:

```
Host comma
  HostName <comma-ip>
  User comma
  IdentityFile ~/.ssh/<your-github-key>
  IdentitiesOnly yes
```

Check: `ssh comma true` returns without asking for a password. (The comma's IP is
shown in its network settings. Without this entry, pass `--host comma@<comma-ip>` to the launcher.)

## 3. Run it

From the repository root:

```bash
tools/starpilot_auto/dhu_launch.sh
```

It will:

1. connect to the comma over SSH (or reuse a connection it opened earlier; connections are shared for 30 minutes),
2. check that the comma is not projecting to a car at the same time,
3. start the comma side and wait until it is ready,
4. open an SSH tunnel (or reuse one already on the port), and
5. open the DHU window, with its console in your terminal.

Within a few seconds the DHU shows "Starting StarPilot display", then the car-sized
StarPilot home screen (the UI takes about 10 seconds to load). Click in the window to use it.

**To stop:** close the DHU window, type `quit` in the terminal, or press Ctrl-C.
The launcher stops the comma side and prints the last frame rate.

### Options

| Option | Default | Meaning |
|---|---|---|
| `--view car` / `--view mirror` | `car` | Car-sized StarPilot UI with touch, or a copy of the comma's own screen (no touch) |
| `--host HOST` | `comma` | An `~/.ssh/config` alias or `comma@<ip>` |
| `--dhu PATH` | searched in `$ANDROID_HOME`, `$ANDROID_SDK_ROOT`, `~/Library/Android/sdk`, `~/Android/Sdk` | The `desktop-head-unit` executable |
| `--dhu-config FILE.ini` | none | DHU screen settings, e.g. a car-sized screen (below) |
| `--port N` | `5288` | Local and comma-side port; use another to run a second **mirror** session |
| `--synthetic` | off | Stream a moving test pattern instead of the UI |
| `--stop-starpilot-auto` | off | Stop the comma's own Starpilot Auto session (to a car) first instead of refusing |

To avoid typing options, put defaults in `~/.config/starpilot/dhu.env`:

```bash
COMMA_HOST=comma
DHU=/path/to/sdk/extras/google/auto/desktop-head-unit
# DHU_CONFIG=/path/to/car-720p.ini
# DHU_VIEW=mirror
# DHU_PORT=5288
```

A short command is handy: `ln -s "$PWD/tools/starpilot_auto/dhu_launch.sh" ~/.local/bin/starpilot-auto-dhu`
(any folder on your `PATH` works).

### A car-sized screen

The DHU defaults to an 800×480 screen. Many cars are 1280×720; to match, save
this as `car-720p.ini` and run `tools/starpilot_auto/dhu_launch.sh --dhu-config car-720p.ini`:

```ini
[general]
    resolution = 1280x720
    dpi = 160
    framerate = 60
    touch = true
```

The comma then negotiates 1280×720 as it does with such a car. Other keys
(margins, night mode, sensors, rotary input) are in
[Google's DHU documentation](https://developer.android.com/training/cars/testing/dhu).

## Using the DHU console

Type commands into the terminal running the DHU; `help` lists them all.

| Command | Does |
|---|---|
| `screenshot /full/path/shot.png` | Save what the DHU shows (a file name is required) |
| `tap X Y` | Touch at screen coordinates (800×480 by default) |
| `focus video toggle` | Take the screen away and give it back, like a car switching to its radio screen |
| `day` / `night` | Day or night mode |
| `quit` | Close the DHU |

Worth checking after changes to Starpilot Auto code:

- **Streaming:** `tail -f` the log path the launcher prints; every 5 s the comma reports
  `"state": "streaming"`, `"view": "car"`, `"encoder": "qcom-v4l2"` and an `fps` around 25–30,
  with `frames_acked` within a frame or two of `frames_sent`.
- **Losing the screen:** `focus video toggle`, wait more than 5 s, toggle again. The comma
  should report `suspended`, then `streaming` again, still in `car` view.
- **Touch:** tap something; the UI responds and `input_events` in the log goes up by 2 per tap.

## Testing the onroad view

The car view's onroad state is `ui_state.started`, i.e. `deviceState.started`, with `ForceOnroad`
ORed in and `ForceOffroad` masked out (`selfdrive/ui/ui_state.py`). To exercise the onroad layouts
on a bench, set `ForceOnroad`. Use System → Drive State → **Onroad** in the car view, the same
control on the comma, or set it directly:

```bash
ssh comma 'echo -n 1 > /data/params/d/ForceOnroad'   # 0 to clear
```

`ForceOnroad` is `CLEAR_ON_MANAGER_START`.

Onroad, `OnroadControls` drops touches on the driving view, and only the quick-menu button
receives input. Its **Go offroad** row is gated on Park. **Resume Onroad** on the home screen
clears both force params. Under the DHU (`STARPILOT_STARPILOT_AUTO_DHU=1`), `vehicle_parked()`
returns true and `navigation_speed()` returns 0, so neither Go offroad nor the Navigate speed
lock needs a `carState`.

The rising edge of `IsOnroad` also fires the daemon's auto-connect. With a car selected,
it starts paging that car over Bluetooth. On the comma's shared radio this degrades Wi-Fi
enough to push DHU acks past `ACK_TIMEOUT`, and the session drops. `dhu_device.py`
therefore holds `/data/starpilot_auto/dhu-<port>.pid` while it runs. `Supervisor._auto_connect()`
suppresses starts while that PID is a live `dhu_device` process (`dhu_session_active()`).

## Protocol check without a comma

`tools/starpilot_auto/dhu_test.py` runs the phone side on your computer with a test
pattern. It checks the identity and the protocol, not the comma. It needs the
identity files on the computer: install them with
`python tools/starpilot_auto/import_identity.py --apk <Starpilot Auto .apk/.xapk/.apkm>`
(writes the git-ignored `.cache/starpilot_auto/identity/`), then:

```bash
PYTHONPATH=.. uv run --no-project --with numpy --with av --with cryptography \
  python tools/starpilot_auto/dhu_test.py --dhu <SDK>/extras/google/auto/desktop-head-unit --seconds 15 --fps 30
```

(`PYTHONPATH=..` works because the repository folder is named `openpilot`; any Python
with `numpy`, `av` and `cryptography` will do instead of `uv`.) A pass ends with
`{"result": "pass", ...}`. Never commit the identity files.

## Doing it by hand (and for agents)

The launcher runs these three pieces; run them yourself to debug, or from an agent.

**1. The comma side** (keeps running; the comma listens on localhost only):

```bash
ssh comma 'cd /data/openpilot && PYTHONPATH=/data/openpilot /usr/local/venv/bin/python -u tools/starpilot_auto/dhu_device.py --view car'
# prints: identity ok, expires ... / waiting for the DHU on 127.0.0.1:5288
```

**2. The tunnel:**

```bash
ssh -N -L 5288:127.0.0.1:5288 comma
```

**3. The DHU:**

```bash
cd <SDK>/extras/google/auto && ./desktop-head-unit --adb=127.0.0.1:5288
```

Things that trip people and agents up:

- **The DHU quits when its input closes.** Started in the background with no terminal, it
  connects, reads end-of-input and exits (`Failed to read from transport`). Give it a FIFO as
  stdin and keep it open; write console commands into the FIFO:

  ```bash
  mkfifo /tmp/dhu.in
  exec 3<>/tmp/dhu.in; ./desktop-head-unit --adb=127.0.0.1:5288 <&3     # background this
  echo "screenshot /tmp/dhu.png" > /tmp/dhu.in
  ```

  The same works for the launcher: `tools/starpilot_auto/dhu_launch.sh <&3`.
- **Use the comma's venv Python** (`/usr/local/venv/bin/python`) with
  `PYTHONPATH=/data/openpilot`. With the system `python3`, the car layout cannot load and the
  view falls back to mirror (`car view failed: renderer exited with 1`).
- **Agent sandboxes often block the local network.** `ssh: … No route to host` while the
  computer itself can reach the comma means the sandbox, not the network.
- **`pkill -f pattern` inside `ssh '…'` can kill its own shell,** because the pattern is in the
  SSH command line (exit code 255). Put a bracket in the pattern: `pkill -f "dhu_[d]evice"`.
- **In zsh, `$VAR` holding a list is not split into words.** Use arrays when passing file lists
  to `tar`/`scp`, and check copies by checksum.
- **One car-view session at a time.** The car layout has one renderer on the comma; a second
  car-view session (another port) takes it over and the first falls back to mirror. Extra
  sessions should use `--view mirror`. The launcher refuses a second car-view session.
- **Onroad, only the quick menu takes touch.** Leave a forced onroad state with its
  **Go offroad** row or by clearing `ForceOnroad` ([Testing the onroad view](#testing-the-onroad-view)).
- **Don't stop DHU instances you didn't start.** Someone may have one open for a phone
  (it listens for adb on port 5277).
- **Ask before changing files on someone's comma.** Running `dhu_device.py` changes nothing;
  copying code into `/data/openpilot` does.

## Logs

- **On the computer:** the launcher prints the path of the comma side's output
  (a status line every 5 s and, at the end, the reason the session stopped).
- **On the comma**, in `/data/starpilot_auto/logs/`: `session-YYYYMMDD-HHMMSS.jsonl` (one per run;
  `receiver: "desktop-head-unit"`) and `car_ui.log` (the car layout's renderer; look here first
  when the view falls back to mirror).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Desktop Head Unit not found` | Install it (step 1), then pass `--dhu PATH` or set `DHU=` in `~/.config/starpilot/dhu.env`. |
| `cannot reach comma over SSH` | Check `ssh comma true` works (step 2): SSH enabled on the comma, key added, right IP. |
| `the comma's software has no tools/starpilot_auto/dhu_device.py` | The comma runs software without Starpilot Auto; update it. |
| `could not read the comma's Starpilot Auto status` | Bluetooth is off on the comma (the service runs only with Bluetooth on), or the software is too old. |
| `Starpilot Auto is projecting to a car` | Stop it in the comma's settings, or add `--stop-starpilot-auto`. |
| `Starpilot Auto identity missing` / `AuthenticationRejected … (status -3)` | Install the identity in The Galaxy → Vehicle Controls → Starpilot Auto Identity. A self-signed test identity is rejected. |
| `another car-view session is running on the comma` | Close the other DHU first, or use `--view mirror`. |
| DHU shows "openpilot Unavailable" and taps do nothing | Onroad, likely via `ForceOnroad`. Use quick menu → **Go offroad**, or clear the param. |
| View says `mirror (car view failed: …)` | See `/data/starpilot_auto/logs/car_ui.log` on the comma. `renderer exited with 3` means another session changed the screen size (one car view at a time). |
| Session ends with `Video acknowledgement older than 1.5 s` | The DHU stopped confirming frames (network hiccup, or the DHU restarting its video, which has been seen right after clicking into its window). Run the launcher again. |
| DHU console: `Failed to read from transport - disconnect` | The comma side ended; the launcher prints why. |
| `port 5288 is taken by something other than ssh` | Another program uses the port; pick another with `--port`. |
