@echo off
setlocal
set "DEST=%LOCALAPPDATA%\Programs\LuminaCoder"
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\LuminaCoder.lnk" 2>nul
del /q "%USERPROFILE%\Desktop\LuminaCoder.lnk" 2>nul
if exist "%DEST%\LuminaCoder.exe" (
  del /q "%DEST%\LuminaCoder.exe" 2>nul
  rmdir "%DEST%" 2>nul
)
echo LuminaCoder has been removed.
pause
endlocal
exit /b 0
