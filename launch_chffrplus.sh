#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null && pwd )"

source "$DIR/launch_env.sh"

export SP_BOOT_TIMING_LOG="${SP_BOOT_TIMING_LOG:-/tmp/starpilot_boot_timing.log}"
: > "$SP_BOOT_TIMING_LOG" 2>/dev/null || true
SP_LAUNCH_LAST_SECONDS=$SECONDS

function sp_boot_timing_line {
  echo "$1"
  printf '%s\n' "$1" >> "$SP_BOOT_TIMING_LOG" 2>/dev/null || true
}

function sp_launch_timing {
  local now=$SECONDS
  local delta=$((now - SP_LAUNCH_LAST_SECONDS))
  sp_boot_timing_line "SP_BOOT_TIMING launch $1 +${delta}s total=${now}s"
  SP_LAUNCH_LAST_SECONDS=$now
}

function agnos_init {
  sp_launch_timing "agnos_init_start"

  # TODO: move this to agnos
  sudo rm -f /data/etc/NetworkManager/system-connections/*.nmmeta

  # set success flag for current boot slot
  sudo abctl --set_success

  # Restore SSH access after a user-triggered reset if keys were backed up to /cache.
  SSH_BACKUP_DIR="/cache/reset_backup"
  if [ -d "$SSH_BACKUP_DIR" ]; then
    sudo mkdir -p /data/params/d
    for key in GithubSshKeys SshEnabled; do
      if [ -f "$SSH_BACKUP_DIR/$key" ]; then
        sudo cp "$SSH_BACKUP_DIR/$key" "/data/params/d/$key"
      fi
    done
    sudo chown comma:comma /data/params/d/GithubSshKeys /data/params/d/SshEnabled 2>/dev/null || true
    sudo chmod 600 /data/params/d/GithubSshKeys /data/params/d/SshEnabled 2>/dev/null || true
    sudo rm -rf "$SSH_BACKUP_DIR"
  fi

  # TODO: do this without udev in AGNOS
  # udev does this, but sometimes we startup faster
  sudo chgrp gpu /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0
  sudo chmod 660 /dev/adsprpc-smd /dev/ion /dev/kgsl-3d0

  # StarPilot variables
  sudo chmod 0777 /cache

  # Check if AGNOS update is required
  AGNOS_CURRENT_VERSION="$(< /VERSION)"
  AGNOS_UPDATE_REQUIRED=1
  for accepted_version in $AGNOS_ACCEPTED_VERSIONS; do
    if [ "$AGNOS_CURRENT_VERSION" = "$accepted_version" ]; then
      AGNOS_UPDATE_REQUIRED=0
      break
    fi
  done

  if [ "$AGNOS_UPDATE_REQUIRED" = "1" ]; then
    AGNOS_PY="$DIR/system/hardware/tici/agnos.py"
    MANIFEST="$DIR/system/hardware/tici/agnos.json"
    if $AGNOS_PY --verify $MANIFEST; then
      sudo reboot
    fi
    $DIR/system/hardware/tici/updater $AGNOS_PY $MANIFEST
  fi

  sp_launch_timing "agnos_init_done"
}

function launch {
  sp_launch_timing "launch_start"

  # Remove orphaned git lock if it exists on boot
  [ -f "$DIR/.git/index.lock" ] && rm -f $DIR/.git/index.lock

  # Check to see if there's a valid overlay-based update available. Conditions
  # are as follows:
  #
  # 1. The DIR init file has to exist, with a newer modtime than anything in
  #    the DIR Git repo. This checks for local development work or the user
  #    switching branches/forks, which should not be overwritten.
  # 2. The FINALIZED consistent file has to exist, indicating there's an update
  #    that completed successfully and synced to disk.

  if [ -f "${DIR}/.overlay_init" ]; then
    find ${DIR}/.git -newer ${DIR}/.overlay_init | grep -q '.' 2> /dev/null
    if [ $? -eq 0 ]; then
      echo "${DIR} has been modified, skipping overlay update installation"
    else
      if [ -f "${STAGING_ROOT}/finalized/.overlay_consistent" ]; then
        if [ ! -d /data/safe_staging/old_openpilot ]; then
          echo "Valid overlay update found, installing"
          LAUNCHER_LOCATION="${BASH_SOURCE[0]}"

          mv $DIR /data/safe_staging/old_openpilot
          mv "${STAGING_ROOT}/finalized" $DIR
          cd $DIR

          echo "Restarting launch script ${LAUNCHER_LOCATION}"
          unset AGNOS_VERSION
          exec "${LAUNCHER_LOCATION}"
        else
          echo "openpilot backup found, not updating"
          # TODO: restore backup? This means the updater didn't start after swapping
        fi
      fi
    fi
  fi
  sp_launch_timing "overlay_check_done"

  # handle pythonpath
  ln -sfn $(pwd) /data/pythonpath
  export BASEDIR="$DIR"
  export PYTHONPATH="$DIR/starpilot/third_party:$PWD"
  sp_launch_timing "pythonpath_done"

  # hardware specific init
  if [ -f /AGNOS ]; then
    agnos_init
  fi
  sp_launch_timing "hardware_init_done"

  # write tmux scrollback to a file
  tmux capture-pane -pq -S-1000 > /tmp/launch_log
  sp_launch_timing "capture_launch_log_done"

  # start manager
  cd system/manager

  sp_launch_timing "launch_param_migrations_start"
  if ! python3 ./launch_param_migrations.py; then
    echo "Launch param migrations failed; continuing boot."
  fi
  sp_launch_timing "launch_param_migrations_done"

  # Bootstrap runtime (e.g. /usr/comma after reset/uninstall) must go straight
  # to manager/setup flow. Do not run StarPilot prebuilt checks/builds here.
  if [ "$DIR" = "/usr/comma" ] || [ ! -d "$DIR/.git" ]; then
    sp_launch_timing "bootstrap_manager_start"
    ./manager.py
    while true; do sleep 1; done
  fi

  function prebuilt_runtime_compatible {
    python3 - <<'PY'
import hashlib
import importlib
import os
from pathlib import Path
import sys
import time

start = time.monotonic()
last = start
log_path = os.environ.get("SP_BOOT_TIMING_LOG")

def emit(line):
  print(line, flush=True)
  if log_path:
    try:
      with open(log_path, "a") as f:
        f.write(line + "\n")
    except OSError:
      pass

def log_step(label):
  global last
  now = time.monotonic()
  emit(f"SP_BOOT_TIMING prebuilt_compat {label} +{now - last:.3f}s total={now - start:.3f}s")
  last = now

mods = [
  "openpilot.common.params_pyx",
  "msgq.ipc_pyx",
  "msgq.visionipc.visionipc_pyx",
  "openpilot.common.transformations.transformations",
  "openpilot.selfdrive.pandad.pandad_api_impl",
  "openpilot.selfdrive.controls.lib.lateral_mpc_lib.c_generated_code.acados_ocp_solver_pyx",
  "openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.c_generated_code.acados_ocp_solver_pyx",
]

for mod in mods:
  try:
    importlib.import_module(mod)
  except Exception as e:
    print(f"Prebuilt compatibility failure in {mod}: {e}", file=sys.stderr)
    raise
  log_step(f"import:{mod}")

repo_root = Path.cwd().parents[1]

def join_chunked_artifacts(root):
  """Rebuild artifacts that are too big for git and ship split into .chunkNNofMM parts.

  Without this the required-files check below fails on a fresh checkout, prebuilt is declared
  incompatible, and every single boot pays for a full local build. Joining is idempotent and
  verified against the shipped .sha256, so a truncated or half-written join is discarded
  rather than trusted.
  """
  joined = []
  for first in sorted(root.glob("**/*.chunk01of*")):
    target = first.parent / first.name.split(".chunk01of")[0]
    if target.is_file():
      continue
    manifest = Path(f"{target}.chunkmanifest")
    try:
      count = int(manifest.read_text().strip())
    except (OSError, ValueError):
      continue
    parts = [Path(f"{target}.chunk{i:02d}of{count:02d}") for i in range(1, count + 1)]
    if not all(p.is_file() for p in parts):
      continue
    want = ""
    sha_file = Path(f"{target}.sha256")
    try:
      want = sha_file.read_text().split()[0].strip()
    except (OSError, IndexError):
      pass
    tmp = target.with_name(f".{target.name}.joining")
    digest = hashlib.sha256()
    try:
      with tmp.open("wb") as out:
        for part in parts:
          with part.open("rb") as src:
            for block in iter(lambda s=src: s.read(1024 * 1024), b""):
              out.write(block)
              digest.update(block)
      if want and digest.hexdigest() != want:
        emit(f"SP_BOOT_TIMING prebuilt_compat chunk_join_sha_mismatch {target.name}")
        tmp.unlink(missing_ok=True)
        continue
      tmp.replace(target)
      joined.append(target.name)
    except OSError as exc:
      emit(f"SP_BOOT_TIMING prebuilt_compat chunk_join_failed {target.name}: {exc}")
      tmp.unlink(missing_ok=True)
  if joined:
    emit(f"SP_BOOT_TIMING prebuilt_compat chunk_join joined={','.join(joined)}")

join_chunked_artifacts(repo_root)
log_step("chunk_join")

required_files = [
  repo_root / "selfdrive/modeld/models/driving_tinygrad.pkl",
  repo_root / "selfdrive/modeld/models/dmonitoring_model_metadata.pkl",
  repo_root / "selfdrive/modeld/models/dmonitoring_model_tinygrad.pkl",
  repo_root / "selfdrive/modeld/models/dm_warp_1928x1208_tinygrad.pkl",
  repo_root / "selfdrive/modeld/models/dm_warp_1344x760_tinygrad.pkl",
  repo_root / "selfdrive/pandad/pandad_api_impl.so",
  repo_root / "selfdrive/controls/lib/lateral_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so",
  repo_root / "selfdrive/controls/lib/lateral_mpc_lib/c_generated_code/libacados_ocp_solver_lat.so",
  repo_root / "selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/acados_ocp_solver_pyx.so",
  repo_root / "selfdrive/controls/lib/longitudinal_mpc_lib/c_generated_code/libacados_ocp_solver_long.so",
  repo_root / "opendbc_repo/opendbc/dbc/gm_global_a_powertrain_generated.dbc",
]

for path in required_files:
  if not path.is_file():
    raise FileNotFoundError(f"Missing prebuilt runtime artifact: {path}")
log_step("required_files")
PY
  }

  USE_PREBUILT=1
  if [ -f /data/params/d/UsePrebuilt ]; then
    USE_PREBUILT=$(tr -d '\n' < /data/params/d/UsePrebuilt)
  fi

  sp_launch_timing "prebuilt_decision_done"
  if [ "$USE_PREBUILT" = "1" ] && [ -f $DIR/prebuilt ] && ! prebuilt_runtime_compatible; then
    echo "Prebuilt runtime artifacts are incompatible on this device; rebuilding locally."
    USE_PREBUILT=0
  fi
  sp_launch_timing "prebuilt_compat_done"

  if [ "$USE_PREBUILT" != "1" ] || [ ! -f $DIR/prebuilt ]; then
    sp_launch_timing "build_start"
    ./build.py
    sp_launch_timing "build_done"
  fi
  sp_launch_timing "manager_start"
  ./manager.py

  # if broken, keep on screen error
  while true; do sleep 1; done
}

launch
