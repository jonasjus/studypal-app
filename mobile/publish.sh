#!/bin/sh
# Builds the iPhone version and publishes it on the personal site: https://jonasjus.github.io/studypal/
#     sh mobile/publish.sh
# The site is its own repository (jonasjus.github.io); this replaces its studypal/ folder and pushes.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SITE=${STUDYPAL_SITE_REPO:-git@github-personal:jonasjus/jonasjus.github.io.git}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

"$ROOT/.venv/bin/python" "$ROOT/mobile/build.py" "$TMP/web"
git clone -q --depth 1 "$SITE" "$TMP/site"
rm -rf "$TMP/site/studypal"
cp -R "$TMP/web" "$TMP/site/studypal"
cd "$TMP/site"
touch .nojekyll  # serve the files as they are
git add -A
if git diff --cached --quiet; then
  echo "Nothing changed."
else
  git commit -q -m "StudyPal for iPhone, from studypal-app $(git -C "$ROOT" rev-parse --short HEAD)"
  git push -q
  echo "Published: https://jonasjus.github.io/studypal/ (live in a minute or two)"
fi
