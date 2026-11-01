#!/bin/bash
# Stop the UV-82HP packet TNC.
if pgrep -x direwolf >/dev/null 2>&1; then
  pkill -x direwolf && echo "direwolf stopped"
else
  echo "direwolf was not running"
fi
