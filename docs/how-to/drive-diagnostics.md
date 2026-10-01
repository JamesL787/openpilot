# Check a drive on the bench

Everything needed to explain a "TAKE CONTROL IMMEDIATELY", a lag spike or a slow Starpilot Auto
connection is written to the drive's **rlog**. rlogs survive unplugging the comma; at most the last
few seconds of a drive are lost. The swaglog files in `/data/log` don't reliably survive: they are
uploaded and then deleted.

## Testers: Send report

Testers don't need SSH. On a phone connected to the comma, open The Galaxy, then **Logs & Diagnostics →
Starpilot Auto**. Describe what happened, choose how many recent drives to include, and tap **Send report**. The zip (usually under 1 MB) arrives in the developer's Discord channel with the note and the device's
dongle ID. **Download** saves the same zip to the phone instead, for when there's no internet.

What the zip contains:

- **starpilot-auto/**: session logs covering pairing, the Wi-Fi handshake and streaming, plus reports and
  settings.
- **bluetooth/**: every pairing prompt and how it ended, and the adapter status.
- **drives/**: a report for each drive, the same as step 2 below. The comma builds these itself, only
  while the car is off.

It never contains passwords, certificates, video or a GPS track.

The Discord webhook is built into `starpilot/system/diagnostics/bundle.py`, base64-encoded. To replace
it without a code change, write a new URL to `/data/diagnostics/webhook_url` on the comma.

Use a webhook belonging to a Discord forum channel. The first upload creates a post named
`<car fingerprint> <last 4 of dongle ID>` (`Device <last 4>` if no car is identified). Every message also lists the car and the head unit from the newest Starpilot Auto session log; subsequent uploads add messages and attachments to that post. The device saves
the thread ID under `/data/diagnostics/threads/`, scoped to both the dongle ID and webhook. Changing
either starts a separate post; switching back reuses its saved thread. A deleted thread is recreated
with at most one retry. Old, unscoped `thread_id` files are ignored because their destination cannot
be verified.

The cache survives restarts and updates that preserve `/data/diagnostics/`. If it is erased, another
post is created: a webhook cannot look up an existing post by dongle ID. Recovering after cache loss
requires a server-side registry or bot. If a successful upload cannot save its thread ID, The Galaxy
shows a warning that the next upload may create another post. To select an existing post manually,
put its thread ID in the override URL's `thread_id` query parameter.

## 1. Copy the drive off the comma

Plug the comma in on the bench and find the route. Routes are listed by the time their first segment
was written:

```bash
ssh comma 'cd /data/media/0/realdata && ls -dt *--0 | head -3'
```

Copy its rlogs into one tar (`<route>` is the name without `--0`):

```bash
ssh comma 'cd /data/media/0/realdata && tar cf - <route>--*/rlog.zst' > docs/Rlogs/<route>-logs.tar
```

For Starpilot Auto problems, also copy that drive's session log:

```bash
scp 'comma:/data/starpilot_auto/logs/session-*' docs/Rlogs/   # or just the newest one
```

`docs/Rlogs/` is excluded from git.

## 2. Read the report

```bash
uv run --no-project --with pycapnp --with zstandard \
  python starpilot/system/diagnostics/drive_report.py docs/Rlogs/<route>-logs.tar \
  --starpilot-auto docs/Rlogs/session-NNNNNN-*.jsonl
```

This needs no openpilot build and doesn't need the comma. A 30-minute drive takes a few seconds.

## What the report shows

- **Timeline:** the report includes these, with wall-clock times:
  - Non-routine alerts.
  - selfdrived `commIssue` entries, listing which inputs were invalid or late.
  - `*InputsInvalid` events from calibrationd, locationd, torqued and lagd.
  - mapd tile changes and per-minute activity.
  - Process restarts.

  In an `*InputsInvalid` event, `age_ms` is how old the input was, and `max_loop_gap_ms` (torqued and
  lagd) is the longest pause in that daemon's own loop:
  - A **large loop gap** means the daemon itself was starved of CPU.
  - A **small loop gap with a large `carState` age** means the publisher (card) was late.
- **Kernel/system journal trouble:** out-of-memory kills, thermal throttling, GPU (kgsl) faults, hung
  tasks.
- **Per segment:** speed, CPU per core, free memory, mapd CPU and the top processes for each minute.
  Cores 4 and 5 run card, controlsd and selfdrived. When they reach about 90%, inputs start arriving
  late. mapd's CPU depends on the offline map tile the car is in: dense city tiles cost several times
  more.
- **Starpilot Auto:** connection attempts, failures, reconnects and why the session ended.
