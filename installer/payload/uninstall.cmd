@echo off
setlocal
set "DEST=%LOCALAPPDATA%\Programs\LuminaCode"
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\LuminaCode.lnk" 2>nul
del /q "%USERPROFILE%\Desktop\LuminaCode.lnk" 2>nul
if exist "%DEST%\LuminaCode.exe" (
  del /q "%DEST%\LuminaCode.exe" 2>nul
  rmdir "%DEST%" 2>nul
)
echo LuminaCode has been removed.
pause
endlocal
exit /b 0
