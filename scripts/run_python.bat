@echo off
REM Cross-platform Python resolver for Windows.
REM On Windows, "python" is the standard command. "python3" is often a
REM Microsoft Store alias that doesn't work. Try python first.
python --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python %*
    exit /b %ERRORLEVEL%
)
python3 --version >nul 2>&1
if %ERRORLEVEL% equ 0 (
    python3 %*
    exit /b %ERRORLEVEL%
)
echo session-buffer: Python 3.10+ required but not found on PATH >&2
echo Install Python from https://python.org or add python3 to PATH >&2
exit /b 1
