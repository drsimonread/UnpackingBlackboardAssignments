@echo off
rem Run unpack-submissions on Windows. Usage, from Command Prompt or PowerShell:
rem   unpack-submissions.cmd gradebook_*.zip -o Grading
rem   unpack-submissions.cmd --remove-converters
rem This starts unpack-submissions.ps1 without changing Windows' script settings.
rem Written with Claude Opus 5.5 (Anthropic).
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0unpack-submissions.ps1" %*
set status=%ERRORLEVEL%
rem Keep the window open when started by double-clicking, so messages can be read.
echo %cmdcmdline% | find /i "%~0" >nul
if not errorlevel 1 pause
exit /b %status%
