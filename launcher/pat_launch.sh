#!/bin/bash
# One-click Pat launcher for the menu entries installed by install_desktop.sh.
#
# usage: pat_launch.sh ic7300-ardop | ic7300-xara | qmx-ardop | qmx-xara | uv82hp-packet | stop
#
# Nothing runs until a shortcut is clicked; clicking one starts that radio + modem and stops
# whatever other Pat stack was running, so only ONE stack runs at a time. The 7300's ARDOP and
# XARA share its sound card, and so do the QMX's.
#
# Clicking the stack that is already running just reopens the browser. It does NOT restart
# anything, so a click can't kill a session in progress.
#
# Transmit power is never touched here; set it on the radio.
# rigctld.service (IC-7300 CAT) stays as it is: it is CAT only and is shared with other apps.
set -u
STACK=${1:-}
C=$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)
STATE=/tmp/pat-launch.current
LOG=$HOME/.local/state/pat-launch.log
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== $(date '+%F %T') pat_launch.sh $STACK (was: $(cat "$STATE" 2>/dev/null || echo none))"

fail() { echo "FAILED: $1"; zenity --error --title="Pat launcher" --text="$1" 2>/dev/null & exit 1; }
rig7300() { timeout 5 rigctl -m 2 -r localhost:4532 "$@"; }
wait_port() {   # wait up to 20 s for a localhost TCP listener
  for _ in $(seq 40); do ss -ltn "sport = :$1" | grep -q LISTEN && return 0; sleep 0.5; done
  return 1
}

stop_all() {
  echo "stopping all Pat stacks"
  sudo -n systemctl stop pat xara-ic7300 ardopcf
  "$C/qmx/stop_pat_qmx.sh"
  "$C/packet/stop_direwolf_uv82.sh"
  pkill -x xara          # strays, e.g. a hand-started RX-only XARA
  rig7300 T 0 >/dev/null 2>&1
  rm -f "$STATE"
}

case "$STACK" in
  ic7300-ardop|ic7300-xara) URL=http://localhost:8080 ;;
  qmx-ardop|qmx-xara)       URL=http://localhost:8081 ;;
  uv82hp-packet)            URL=http://localhost:8080 ;;
  stop) exec 9>/tmp/pat-launch.lock; flock 9; stop_all
        zenity --info --title="Pat launcher" --text="All Pat radio stacks stopped." 2>/dev/null &
        exit 0 ;;
  *) fail "unknown stack '$STACK'" ;;
esac

exec 9>/tmp/pat-launch.lock
flock -n 9 || { echo "another launch in progress"; exit 0; }

healthy() {
  case "$STACK" in
    ic7300-ardop) systemctl -q is-active pat && systemctl -q is-active ardopcf ;;
    ic7300-xara)  systemctl -q is-active pat && systemctl -q is-active xara-ic7300 ;;
    qmx-*)        kill -0 "$(cat /tmp/qmx-pat-stack/pat.pid 2>/dev/null)" 2>/dev/null ;;
    uv82hp-packet) systemctl -q is-active pat && pgrep -x direwolf >/dev/null ;;
  esac
}

if [ "$(cat "$STATE" 2>/dev/null)" = "$STACK" ] && healthy; then
  echo "$STACK already running; just opening $URL"
  xdg-open "$URL"; exit 0
fi

# Check the radio is actually there before tearing anything down.
case "$STACK" in
  ic7300-*) [ -e /dev/ic7300 ] && grep -q '^CODEC$' /proc/asound/card*/id 2>/dev/null \
              || fail "IC-7300 not found. Is it powered on and plugged in?" ;;
  qmx-*)    [ -e /dev/qmx ] && grep -q '^Transceiver$' /proc/asound/card*/id 2>/dev/null \
              || fail "QMX not found. Is it powered on and plugged in?" ;;
  uv82hp-*) grep -q '^digirig$' /proc/asound/card*/id 2>/dev/null \
              || fail "Digirig (UV-82HP) not found. Is it plugged in?" ;;
esac

stop_all
sleep 2

case "$STACK" in
  ic7300-ardop|ic7300-xara)
    modem=ardopcf; port=8515
    [ "$STACK" = ic7300-xara ] && { modem=xara-ic7300; port=8300; }
    sudo -n systemctl start rigctld
    wait_port 4532 || fail "rigctld for the IC-7300 did not come up"
    # Data mode with the full 3 kHz passband. Plain USB broke decoding, and the PKTUSB passband
    # has come back as narrow as 1200 Hz, which starves 2300/2750 Hz VARA.
    rig7300 M PKTUSB 3000 >/dev/null || echo "warning: could not set PKTUSB 3000"
    sudo -n systemctl start "$modem" || fail "$modem failed to start (see: journalctl -u $modem)"
    wait_port $port || fail "$modem did not open port $port (see: journalctl -u $modem)"
    sudo -n systemctl start pat ;;
  qmx-ardop|qmx-xara)
    "$C/qmx/start_pat_qmx.sh" "${STACK#qmx-}" || fail "QMX stack failed to start (see $LOG)" ;;
  uv82hp-packet)
    "$C/packet/start_direwolf_uv82.sh" || fail "Direwolf failed to start (see $LOG)"
    sudo -n systemctl start pat ;;
esac

wait_port "${URL##*:}" || fail "Pat web UI did not come up on ${URL##*:}"
echo "$STACK" > "$STATE"
echo "$STACK up; opening $URL"
xdg-open "$URL"
