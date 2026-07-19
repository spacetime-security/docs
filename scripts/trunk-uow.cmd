@echo off
where py >nul 2>nul
if %errorlevel% equ 0 (
  py -3 "%~dp0trunk-uow" %*
  exit /b %errorlevel%
)
python "%~dp0trunk-uow" %*
exit /b %errorlevel%
