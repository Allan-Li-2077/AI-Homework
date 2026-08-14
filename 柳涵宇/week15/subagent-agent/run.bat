@echo off
setlocal

cd /d "%~dp0"
if errorlevel 1 exit /b 1

set "PYTHON_CMD="
where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
) else (
  where py >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
  echo Python is not installed or not on PATH.
  echo.
  pause
  exit /b 1
)

if "%PYTHON_CMD%"=="py -3" (
  py -3 -m work.subagent_agent.core %*
) else (
  python -m work.subagent_agent.core %*
)

set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo Run completed.
) else (
  echo Run failed with exit code %EXIT_CODE%.
)
pause
exit /b %EXIT_CODE%
