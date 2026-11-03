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
# The oldest macOS it runs on: the newest that any of its parts was built for. With this set, an older Mac
# says so plainly instead of failing to open the app.
MIN=$(find dist/StudyPal.app -type f \( -name '*.so' -o -name '*.dylib' -o -perm +111 \) -exec vtool -show-build {} \; 2>/dev/null \
      | awk '/minos/ {print $2}' | sort -t. -k1,1n -k2,2n | tail -1)
if [ -n "$MIN" ]; then
    /usr/libexec/PlistBuddy -c "Add :LSMinimumSystemVersion string $MIN" dist/StudyPal.app/Contents/Info.plist 2>/dev/null \
        || /usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion $MIN" dist/StudyPal.app/Contents/Info.plist
fi
# Changing Info.plist breaks PyInstaller's signature, and macOS calls an app with a broken signature "damaged"
# (with no way to open it). Sign it again: ad hoc, as there's no developer certificate.
codesign --force --deep --sign - dist/StudyPal.app
codesign --verify --deep --strict dist/StudyPal.app
rm -f dist/StudyPal-mac.zip
ditto -c -k --keepParent dist/StudyPal.app dist/StudyPal-mac.zip
echo "Built dist/StudyPal.app ($(lipo -archs dist/StudyPal.app/Contents/MacOS/StudyPal), macOS ${MIN:-?} or newer) and dist/StudyPal-mac.zip"
