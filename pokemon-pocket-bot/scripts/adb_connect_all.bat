@echo off
REM Conecta rapidamente nas portas conhecidas dos emuladores (Windows).
set ADB=adb
for %%p in (7555 16384 16416 16448 16480 5555 5557 5559 5561 5563 5565 5575 5585 62001 62025 21503 21513 5554 5556) do (
  start /b "" %ADB% connect 127.0.0.1:%%p >nul 2>&1
)
timeout /t 3 >nul
%ADB% devices
