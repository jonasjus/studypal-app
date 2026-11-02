#!/bin/sh
# Builds dist/StudyPal.app and a zip of it to send to someone. Run from the project folder:
#     sh packaging/build-mac.sh
set -e
cd "$(dirname "$0")/.."
PY=${PYTHON:-.venv/bin/python}
"$PY" -m PyInstaller --noconfirm --clean --windowed \
    --name StudyPal \
    --icon packaging/StudyPal.icns \
    --osx-bundle-identifier app.studypal \
    --add-data "src/studypal/web:studypal/web" \
    --add-data "src/studypal/cloud.json:studypal" \
    --paths src \
    --distpath dist --workpath build \
    packaging/launch.py
# Tell macOS the window looks right in both light and dark mode.
/usr/libexec/PlistBuddy -c "Add :NSRequiresAquaSystemAppearance bool false" dist/StudyPal.app/Contents/Info.plist 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $("$PY" -c 'import sys; sys.path.insert(0, "src"); import studypal; print(studypal.__version__)')" dist/StudyPal.app/Contents/Info.plist
rm -f dist/StudyPal-mac.zip
ditto -c -k --keepParent dist/StudyPal.app dist/StudyPal-mac.zip
echo "Built dist/StudyPal.app and dist/StudyPal-mac.zip"
