#!/bin/sh
# Builds the iPhone version and publishes it at https://studypal.justesen.no/
#     sh mobile/publish.sh
# The site is its own repository (jonasjus/studypal-web), served by GitHub Pages with that domain. This
# replaces everything in it with a fresh build and pushes.
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SITE=${STUDYPAL_SITE_REPO:-git@github-personal:jonasjus/studypal-web.git}
DOMAIN=${STUDYPAL_DOMAIN:-studypal.justesen.no}
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

"$ROOT/.venv/bin/python" "$ROOT/mobile/build.py" "$TMP/web"
git clone -q --depth 1 "$SITE" "$TMP/site" 2>/dev/null || { mkdir "$TMP/site" && git -C "$TMP/site" init -q -b main \
  && git -C "$TMP/site" remote add origin "$SITE"; }
find "$TMP/site" -mindepth 1 -maxdepth 1 ! -name .git -exec rm -rf {} +
cp -R "$TMP/web/." "$TMP/site/"
echo "$DOMAIN" > "$TMP/site/CNAME"  # the custom domain GitHub Pages serves it on
touch "$TMP/site/.nojekyll"          # serve the files as they are
cd "$TMP/site"
git add -A
if git diff --cached --quiet; then
  echo "Nothing changed."
else
  git commit -q -m "StudyPal for iPhone, from studypal-app $(git -C "$ROOT" rev-parse --short HEAD)"
  git push -q -u origin main
  echo "Published: https://$DOMAIN/ (live in a minute or two)"
fi
