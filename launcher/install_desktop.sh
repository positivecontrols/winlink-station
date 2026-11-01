#!/bin/bash
# Install the Pat menu entries for this checkout.
set -eu
here=$(cd "$(dirname "$(readlink -f "$0")")" && pwd)
dest="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$dest"
for f in "$here"/desktop/*.desktop.in; do
  out="$dest/$(basename "${f%.in}")"
  sed "s|@LAUNCHER@|$here/pat_launch.sh|" "$f" > "$out"
  echo "installed $out"
done
