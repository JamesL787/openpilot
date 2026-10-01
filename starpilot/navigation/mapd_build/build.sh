#!/usr/bin/env bash
# Builds starpilot/navigation/mapd: pfeifer mapd at a pinned release plus the patches in this directory.
# Needs Docker; produces a static linux/arm64 binary.
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
MAPD_REPO="https://github.com/pfeiferj/mapd.git"
MAPD_COMMIT="7201c6b4b4ec1b0b9ea21daa8c05b80fdd7e01ee"  # v2.3.1

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --quiet "$MAPD_REPO" "$WORK/mapd"
cd "$WORK/mapd"
git checkout --quiet "$MAPD_COMMIT"
for patch in "$DIR"/*.patch; do
  git apply "$patch"
done

docker run --rm --platform linux/arm64 -v "$WORK/mapd":/src -w /src golang:1.25 sh -c '
  apt-get update -qq >/dev/null && apt-get install -y -qq zlib1g-dev >/dev/null &&
  go build -tags "netgo osusergo" -ldflags="-extldflags=-static -s -w" -o build/mapd'

cp "$WORK/mapd/build/mapd" "$DIR/../mapd"
chmod +x "$DIR/../mapd"
file "$DIR/../mapd"
