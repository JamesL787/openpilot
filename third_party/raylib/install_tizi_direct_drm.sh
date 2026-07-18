#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WHEEL="$DIR/wheel/raylib-5.5.0.2-cp312-cp312-linux_aarch64.whl"
WHEEL_SHA256="784fb82c7bb52d2936c6be42d9e91fb47f610efca466d230c8ffd03cfb4f10f9"
PYTHON="/usr/local/venv/bin/python"

if [[ ! -f /TICI ]] || [[ "$(uname -m)" != "aarch64" ]]; then
  echo "This installer is only for comma 3/3X hardware."
  exit 1
fi

if [[ ! -f "$WHEEL" ]]; then
  echo "Missing raylib wheel: $WHEEL"
  exit 1
fi

echo "$WHEEL_SHA256  $WHEEL" | sha256sum --check --status

SUDO=""
if [[ $(id -u) -ne 0 ]]; then
  SUDO="sudo"
fi

ROOT_REMOUNTED=0
restore_root() {
  if [[ "$ROOT_REMOUNTED" -eq 1 ]]; then
    sync
    $SUDO mount -o remount,ro /
  fi
}
trap restore_root EXIT

$SUDO mount -o remount,rw /
ROOT_REMOUNTED=1

$SUDO "$PYTHON" -m pip install --force-reinstall --no-deps "$WHEEL"
$SUDO install -m 0644 "$DIR/magic.service" /etc/systemd/system/magic.service
$SUDO systemctl daemon-reload
$SUDO systemctl disable weston.service weston-ready.service
$SUDO systemctl enable magic.service

echo "Direct-DRM raylib is installed. Reboot the device to activate it."
