#!/bin/bash
# Start Direwolf as the 2m packet TNC: Digirig Mobile + Baofeng UV-82HP.
# Feeds Pat (port 8080) over AGWPE on localhost:8000.
#
# RADIO SETUP THIS ASSUMES (none of it is software-enforceable):
#   Your packet frequency, simplex, in BOTH VFOs, no offset, no tone
#   TDR / dual-watch OFF   (dual watch time-slices RX and punches holes in packets)
#   Squelch 0 (open)       (a closing squelch chops the start of incoming frames)
#   Volume knob at 40%     (this is a CALIBRATION setting; bumping it breaks decode)
set -u
CONF="${DIREWOLF_CONF:-$(dirname "$(readlink -f "$0")")/direwolf-digirig.conf}"
LOG="${DIREWOLF_LOG:-/tmp/direwolf.log}"

if grep -Eq '^MYCALL[[:space:]]+N0CALL' "$CONF"; then
  echo "set MYCALL in $CONF before transmitting" >&2
  exit 1
fi

if pgrep -x direwolf >/dev/null 2>&1; then
  echo "direwolf already running (pid $(pgrep -x direwolf | head -1))"
  exit 0
fi

# Re-pin the calibrated audio levels on every start. alsa-restore runs before the
# USB card enumerates, so stored ALSA state does NOT reliably come back on its own
# -- the same race that silently broke ardopcf's PCM level after a cold reboot.
# Mic=7 / AGC off was calibrated against a NOAA carrier and confirmed by Direwolf
# reporting audio level 55 on live APRS traffic (its ideal is ~50).
amixer -c digirig sset 'Mic' 7 cap            >/dev/null 2>&1
amixer -c digirig sset 'Auto Gain Control' off >/dev/null 2>&1

nohup direwolf -c "$CONF" -t 0 >"$LOG" 2>&1 &
sleep 2

if pgrep -x direwolf >/dev/null 2>&1; then
  echo "direwolf started -- AGWPE on 8000, log: $LOG"
else
  echo "direwolf FAILED to start -- see $LOG" >&2
  exit 1
fi
