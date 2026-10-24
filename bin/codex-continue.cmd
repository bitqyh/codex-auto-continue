@echo off
setlocal
set "ROOT=%~dp0.."
set "PYTHONPATH=%ROOT%\src;%PYTHONPATH%"
where python >nul 2>nul
if errorlevel 1 goto try_py
python -m codex_auto_continue %*
exit /b %errorlevel%
:try_py
where py >nul 2>nul
if errorlevel 1 goto missing
py -3 -m codex_auto_continue %*
exit /b %errorlevel%
:missing
echo codex-auto-continue: Python 3.9+ was not found ^(python/py^). 1>&2
exit /b 127
