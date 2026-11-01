#!/bin/bash
# Stop the QMX Pat/ARDOP stack started by start_pat_qmx.sh.
# Kills by tracked PID, not by process name -- pkill -f/-x would risk
# matching the IC-7300's separate rigctld/ardopcf/pat instances too.

PIDDIR=/tmp/qmx-pat-stack

if [ ! -d "$PIDDIR" ]; then
  echo "Nothing to stop (no $PIDDIR)." >&2
  exit 0
fi

# Unkey first (XARA/ardop key via this rigctld), while rigctld is still up.
timeout 3 rigctl -m 2 -r localhost:4533 T 0 >/dev/null 2>&1

for name in pat xara ardopcf rigctld; do
  f="$PIDDIR/$name.pid"
  if [ -f "$f" ]; then
    pid=$(cat "$f")
    if kill -0 "$pid" 2>/dev/null; then
      echo "Stopping $name (pid $pid)..."
      kill "$pid"
    else
      echo "$name (pid $pid) already gone."
    fi
    rm -f "$f"
  fi
done
echo "Done."
