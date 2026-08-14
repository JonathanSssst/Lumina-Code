@echo off
setlocal
set "DEST=%LOCALAPPDATA%\Programs\LuminaCode"
if not exist "%DEST%" mkdir "%DEST%"
copy /y "%~dp0LuminaCode.exe" "%DEST%\LuminaCode.exe" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%APPDATA%\Microsoft\Windows\Start Menu\Programs\LuminaCode.lnk'); $s.TargetPath='%DEST%\LuminaCode.exe'; $s.WorkingDirectory='%DEST%'; $s.Save(); $d=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\LuminaCode.lnk'); $d.TargetPath='%DEST%\LuminaCode.exe'; $d.WorkingDirectory='%DEST%'; $d.Save()"
echo.
echo LuminaCode 1.0.9 installed to %DEST%
echo A shortcut was added to the Start Menu and Desktop.
echo.
pause
endlocal
exit /b 0
