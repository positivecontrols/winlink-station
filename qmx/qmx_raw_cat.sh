#!/bin/bash
# Safe wrapper for sending a raw QMX CAT command through the standing rigctld
# connection (localhost:4533). ALWAYS forces the ';' terminator so rigctl
# never appends its default CR -- an incoming CR flips the QMX's serial port
# into terminal/menu mode, which caused a firmware hang on 2026-09-05.
# Usage: qmx_raw_cat.sh SS0     (Set-type, will hang ~timeout, that's normal)
#        qmx_raw_cat.sh SS      (Get-type, replies immediately)
if [ -z "$1" ]; then
  echo "usage: $0 <command-without-semicolon>" >&2
  exit 1
fi
timeout 3 rigctl -m 2 -r localhost:4533 -t ';' w "$1"
