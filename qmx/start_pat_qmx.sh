#!/bin/bash
# Bring up the QMX side of Pat/ARDOP -- separate from the IC-7300's systemd
# stack (rigctld:4532, ardopcf:8515, pat:8080) so both rigs can be used
# independently without disturbing each other.
#
# QMX side uses: rigctld:4533, ardopcf:8615 (data 8616, webgui 8614),
# pat http on :8081 with ~/.config/pat/config-qmx.json.
#
# NOT run as systemd units (unlike the IC-7300 stack) because the QMX is the
# occasional/portable rig, not always connected -- on-demand start/stop is a
# better fit than a permanently-enabled service racing a USB device that may
# not be there.
#
# NOTE: the QMX's USB connection has been observed to drop and re-enumerate
# on its own (seen twice within 24h -- unclear cause, maybe USB power
# management or a firmware quirk). /dev/qmx (99-qmx.rules) follows it to
# whatever /dev/ttyACMn it lands on next, but a rigctld ALREADY RUNNING keeps
# its now-dead file handle open and won't recover on its own -- it doesn't
# crash, it just silently fails. Symptom: "QSY failure" or similar in Pat.
# Fix: stop_pat_qmx.sh && start_pat_qmx.sh to pick up the current device.
#
# WARNING: ardopcf's TRAILER timing has NOT been calibrated for the QMX.
# The IC-7300 needed TRAILER 120 (see ardopcf.service comments) because of
# that radio's specific PTT/audio latency. The QMX has completed a Winlink
# message at the default, but that is one result, not a calibration.
#
# NOTE: the QMX has been found sitting in FSK mode (not USB) after some
# earlier, unrelated CAT session -- ARDOP-over-soundcard needs it in USB or
# every frame decode fails despite real, strong RF output. set_usb_mode.py
# forces it back before rigctld grabs the serial port (they can't both hold
# /dev/qmx at once). See that script's docstring for the full incident.

# usage: start_pat_qmx.sh [ardop|xara]   (default ardop)
# xara = the XARA VARA HF modem on port 8400 (config-qmx.json's varahf addr) instead of ardopcf.
# XARA on the QMX is NOT yet tested on air (proven on the IC-7300 only).

set -e
MODEM=${1:-ardop}
case "$MODEM" in ardop|xara) ;; *) echo "usage: $0 [ardop|xara]" >&2; exit 2;; esac
PIDDIR=/tmp/qmx-pat-stack

if [ "$MODEM" = xara ]; then
  # Pat's config already holds the callsign, and a desktop launcher has no shell environment.
  MYCALL=${MYCALL:-$(python3 -c 'import json, os; print(json.load(open(os.path.expanduser("~/.config/pat/config-qmx.json"))).get("mycall", ""))' 2>/dev/null || true)}
  if [ -z "$MYCALL" ]; then
    echo "set mycall in ~/.config/pat/config-qmx.json" >&2
    exit 1
  fi
fi
mkdir -p "$PIDDIR"

if [ -f "$PIDDIR/rigctld.pid" ] && kill -0 "$(cat "$PIDDIR/rigctld.pid")" 2>/dev/null; then
  echo "Already running (see $PIDDIR/*.pid). Run stop_pat_qmx.sh first." >&2
  exit 1
fi

echo "Forcing QMX into USB mode (required for ARDOP; see script docstring)..."
python3 "$(dirname "$0")/set_usb_mode.py" || echo "  (continuing anyway -- check radio is plugged in)"

echo "Starting rigctld for QMX (Kenwood TS-440S model, /dev/qmx, port 4533)..."
rigctld -m 2002 -r /dev/qmx -s 38400 -t 4533 -C poll_interval=0 > /tmp/qmx_rigctld.log 2>&1 &
echo $! > "$PIDDIR/rigctld.pid"
sleep 1

if [ "$MODEM" = xara ]; then
  echo "Starting XARA for QMX (card 'Transceiver', command port 8400, KISS off)..."
  "${XARA_BIN:-xara}" --call "$MYCALL" --hf 2300 --audio alsa \
    --capture plughw:CARD=Transceiver,DEV=0 --playback plughw:CARD=Transceiver,DEV=0 \
    --radio --ptt rigctld:127.0.0.1:4533 --ptt-max-s 30 --port 8400 --kiss-port off \
    > /tmp/qmx_xara.log 2>&1 &
  echo $! > "$PIDDIR/xara.pid"
  MODEM_LOG=/tmp/qmx_xara.log
else
  echo "Starting ardopcf for QMX (card 'Transceiver', ports 8615/8614)..."
  ardopcf 8615 plughw:Transceiver,0 plughw:Transceiver,0 -G 8614 -l /tmp > /tmp/qmx_ardopcf.log 2>&1 &
  echo $! > "$PIDDIR/ardopcf.pid"
  MODEM_LOG=/tmp/qmx_ardopcf.log
fi
sleep 1

echo "Starting pat http on :8081 (config-qmx.json)..."
pat --config ~/.config/pat/config-qmx.json http --addr :8081 > /tmp/qmx_pat.log 2>&1 &
echo $! > "$PIDDIR/pat.pid"

sleep 2
echo
echo "PIDs: $(cat "$PIDDIR"/*.pid | tr '\n' ' ')"
echo "Web UI: http://<pi-host>:8081"
echo "Logs: /tmp/qmx_rigctld.log $MODEM_LOG /tmp/qmx_pat.log"
echo "Stop with: stop_pat_qmx.sh"
