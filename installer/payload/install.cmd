@echo off
setlocal
set "DEST=%LOCALAPPDATA%\Programs\LuminaCoder"
if not exist "%DEST%" mkdir "%DEST%"
copy /y "%~dp0LuminaCoder.exe" "%DEST%\LuminaCoder.exe" >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%APPDATA%\Microsoft\Windows\Start Menu\Programs\LuminaCoder.lnk'); $s.TargetPath='%DEST%\LuminaCoder.exe'; $s.WorkingDirectory='%DEST%'; $s.Save(); $d=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\LuminaCoder.lnk'); $d.TargetPath='%DEST%\LuminaCoder.exe'; $d.WorkingDirectory='%DEST%'; $d.Save()"
echo.
echo LuminaCoder 1.0.0 installed to %DEST%
echo A shortcut was added to the Start Menu and Desktop.
echo.
pause
endlocal
exit /b 0
