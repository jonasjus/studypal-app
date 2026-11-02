@echo off
rem Builds dist\StudyPal\StudyPal.exe on Windows. Run from the project folder, after:
rem     py -3.11 -m venv .venv
rem     .venv\Scripts\pip install -e ".[dev]"
rem then:  packaging\build-windows.bat
cd /d "%~dp0\.."
.venv\Scripts\python -m PyInstaller --noconfirm --clean --windowed ^
    --name StudyPal ^
    --icon packaging\icon.png ^
    --add-data "src\studypal\web;studypal\web" ^
    --add-data "src\studypal\cloud.json;studypal" ^
    --paths src ^
    --distpath dist --workpath build ^
    packaging\launch.py
powershell -Command "Compress-Archive -Force -Path dist\StudyPal -DestinationPath dist\StudyPal-windows.zip"
echo Built dist\StudyPal\StudyPal.exe and dist\StudyPal-windows.zip
