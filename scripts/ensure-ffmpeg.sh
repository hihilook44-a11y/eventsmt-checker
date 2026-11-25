#!/usr/bin/env bash
# Prefer distro packages with bounded network waits; verify the static fallback.
set -euo pipefail
if command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
  ffmpeg -version | head -n1
  ffprobe -version | head -n1
  exit 0
fi
# GitHub-hosted runners can lack ffmpeg. Distro packages avoid reliance on
# short-lived upstream autobuild assets; timeouts preserve a bounded fallback.
if command -v apt-get >/dev/null && command -v sudo >/dev/null && command -v timeout >/dev/null; then
  if timeout 90s sudo -n apt-get update -qq &&
     timeout 180s sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg &&
     command -v ffmpeg >/dev/null && command -v ffprobe >/dev/null; then
    ffmpeg -version | head -n1
    ffprobe -version | head -n1
    exit 0
  fi
  echo 'Distro ffmpeg unavailable; trying checksum-pinned static fallback.' >&2
fi
bin="${RUNNER_TEMP:-/tmp}/eventsmt-ffmpeg/bin"
if [ ! -x "$bin/ffmpeg" ] || [ ! -x "$bin/ffprobe" ]; then
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  url='https://github.com/FFmpeg-Builds/FFmpeg-Builds/releases/download/autobuild-2026-11-25-12-41/ffmpeg-n8.1.3-41-ga8029b6528-linux64-gpl-8.1.tar.xz'
  curl -fL --retry 2 --connect-timeout 15 --max-time 180 "$url" -o "$tmp/ffmpeg.tar.xz"
  echo "52e5d6c80ef213861dcdbdf5f742c551469ee7de91b3a846256660c9d0943997  $tmp/ffmpeg.tar.xz" | sha256sum --check --strict
  mkdir -p "$bin"
  tar -xJf "$tmp/ffmpeg.tar.xz" --strip-components=2 -C "$bin" --wildcards '*/bin/ffmpeg' '*/bin/ffprobe'
  chmod 755 "$bin/ffmpeg" "$bin/ffprobe"
fi
"$bin/ffmpeg" -version | head -n1
"$bin/ffprobe" -version | head -n1
if [ -n "${GITHUB_PATH:-}" ]; then echo "$bin" >> "$GITHUB_PATH"; fi
