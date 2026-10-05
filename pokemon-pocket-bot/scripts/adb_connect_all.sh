#!/usr/bin/env bash
# Conecta rapidamente nas portas conhecidas dos emuladores (sem Python).
set -u
ADB=${ADB:-adb}
PORTS="7555 16384 16416 16448 16480 5555 5557 5559 5561 5563 5565 5575 5585 62001 62025 21503 21513 5554 5556"
for p in $PORTS; do
  "$ADB" connect "127.0.0.1:$p" >/dev/null 2>&1 &
done
wait
"$ADB" devices
