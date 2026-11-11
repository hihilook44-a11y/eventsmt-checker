#!/usr/bin/env bash
# Avoid apt mirror/DNS hangs in ephemeral runners. Verify a pinned static build.
set -euo pipefail
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ffmpeg -version | head -n1
  ffprobe -version | head -n1
  exit 0
fi
bin="${RUNNER_TEMP:-/tmp}/eventsmt-ffmpeg/bin"
if [ ! -x "$bin/ffmpeg" ] || [ ! -x "$bin/ffprobe" ]; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  url='https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-11-12-39/ffmpeg-n8.1.3-35-gf1acb0a266-linux64-gpl-8.1.tar.xz'
  curl -fL --retry 2 --connect-timeout 15 --max-time 180 "$url" -o "$tmp/ffmpeg.tar.xz"
  echo "32430dc6642d835511470728811e1555ec7ec09d4d27638b059f0e577a98d4e7  $tmp/ffmpeg.tar.xz" | sha256sum --check --strict
  mkdir -p "$bin"
  tar -xJf "$tmp/ffmpeg.tar.xz" --strip-components=2 -C "$bin" --wildcards '*/bin/ffmpeg' '*/bin/ffprobe'
  chmod 755 "$bin/ffmpeg" "$bin/ffprobe"
fi
"$bin/ffmpeg" -version | head -n1
"$bin/ffprobe" -version | head -n1
if [ -n "${GITHUB_PATH:-}" ]; then echo "$bin" >> "$GITHUB_PATH"; fi
