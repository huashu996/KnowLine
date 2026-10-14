@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\StartKnowline.ps1" -ProjectRoot "%~dp0." %*
if errorlevel 1 (
  echo.
  echo Knowline could not start. See the error above and resource\.knowledge\startup.log.
  if not defined KNOWLINE_NO_PAUSE pause
  exit /b 1
)
exit /b 0
