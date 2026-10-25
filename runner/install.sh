#!/bin/sh
# Installs megoocolab-runner from the latest runner release of
# github.com/mmhy2003/MegooColab.
#
#   sh install.sh            install to ~/.local/bin
#   sh install.sh --system   install to /usr/local/bin (uses sudo)
#
# MEGOO_RUNNER_VERSION=1.2.3 pins a version instead of the latest release.
set -eu

REPO="mmhy2003/MegooColab"
SYSTEM=0

for arg in "$@"; do
  case "$arg" in
    --system) SYSTEM=1 ;;
    -h|--help)
      echo "usage: sh install.sh [--system]"
      echo "  installs megoocolab-runner to ~/.local/bin, or /usr/local/bin with --system (sudo)"
      echo "  MEGOO_RUNNER_VERSION=1.2.3 pins a version instead of the latest runner release"
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

fail() { echo "error: $*" >&2; exit 1; }

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) fail "unsupported OS $(uname -s); on Windows use Scoop (see runner/README.md)" ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch=amd64 ;;
  arm64|aarch64) arch=arm64 ;;
  *) fail "unsupported architecture $(uname -m)" ;;
esac

if command -v curl >/dev/null 2>&1; then
  fetch() { curl -fsSL "$1" -o "$2"; }
  fetch_stdout() { curl -fsSL "$1"; }
elif command -v wget >/dev/null 2>&1; then
  fetch() { wget -q "$1" -O "$2"; }
  fetch_stdout() { wget -qO- "$1"; }
else
  fail "curl or wget is required"
fi

if command -v sha256sum >/dev/null 2>&1; then
  sha256() { sha256sum "$1" | cut -d ' ' -f 1; }
elif command -v shasum >/dev/null 2>&1; then
  sha256() { shasum -a 256 "$1" | cut -d ' ' -f 1; }
else
  fail "sha256sum or shasum is required"
fi

version="${MEGOO_RUNNER_VERSION:-}"
version="${version#runner-v}"
version="${version#v}"
if [ -z "$version" ]; then
  # The repository also holds other projects, so pick the newest release whose
  # tag starts with runner-v.
  tag=$(fetch_stdout "https://api.github.com/repos/$REPO/releases?per_page=100" \
    | grep -o '"tag_name": *"runner-v[^"]*"' | head -n 1 | sed 's/.*"\(runner-v[^"]*\)"$/\1/') || true
  [ -n "$tag" ] || fail "no runner release found for $REPO"
  version="${tag#runner-v}"
fi

archive="megoocolab-runner_${version}_${os}_${arch}.tar.gz"
base="https://github.com/$REPO/releases/download/runner-v$version"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
trap 'rm -rf "$tmp"; exit 1' INT TERM

echo "Downloading megoocolab-runner $version ($os/$arch)"
fetch "$base/$archive" "$tmp/$archive" || fail "cannot download $base/$archive"
fetch "$base/checksums.txt" "$tmp/checksums.txt" || fail "cannot download checksums.txt"

expected=$(grep "  $archive\$" "$tmp/checksums.txt" | cut -d ' ' -f 1)
[ -n "$expected" ] || fail "$archive is not listed in checksums.txt"
actual=$(sha256 "$tmp/$archive")
[ "$expected" = "$actual" ] || fail "checksum mismatch for $archive"

tar -xzf "$tmp/$archive" -C "$tmp" megoocolab-runner

if [ "$SYSTEM" -eq 1 ]; then
  dest=/usr/local/bin
  if [ "$(id -u)" -eq 0 ]; then
    install -d "$dest"; install -m 755 "$tmp/megoocolab-runner" "$dest/megoocolab-runner"
  else
    sudo install -d "$dest"; sudo install -m 755 "$tmp/megoocolab-runner" "$dest/megoocolab-runner"
  fi
else
  dest="$HOME/.local/bin"
  mkdir -p "$dest"
  install -m 755 "$tmp/megoocolab-runner" "$dest/megoocolab-runner"
fi

echo "Installed $dest/megoocolab-runner"
case ":$PATH:" in
  *":$dest:"*) ;;
  *) echo "Note: $dest is not on your PATH." ;;
esac
echo "Next: megoocolab-runner login --url URL --token TOKEN, then megoocolab-runner doctor"
