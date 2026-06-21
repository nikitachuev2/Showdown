@echo off
setlocal

if not exist .venv (
  py -m venv .venv
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pytest
python -m PyInstaller ShowdownApp.spec --noconfirm
python -m PyInstaller ShowdownApp.onefile.spec --noconfirm --distpath dist_onefile
if not exist release mkdir release
copy /Y dist_onefile\ShowdownApp.exe release\showdown-latest.exe

echo Build completed. Portable executable: release\showdown-latest.exe
