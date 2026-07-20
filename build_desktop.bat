@echo off
setlocal
cd /d %~dp0

echo === Step 1/3: Build backend (frontend + PyInstaller) ===
call build_windows.bat
if errorlevel 1 exit /b 1

echo === Step 2/3: Install desktop dependencies ===
cd desktop
call npm install
if errorlevel 1 exit /b 1

echo === Step 3/3: Package Electron app (NSIS installer) ===
call npm run package
if errorlevel 1 exit /b 1
cd ..

echo Done. Installer in desktop\build-artifacts\
