#!/bin/bash
# Double-click to rebuild the dashboard from the newest CSV in /data AND publish it to your
# live GitHub Pages link (build + git commit + git push).
#
# Requires: git installed, and this folder already connected to your GitHub repo
# (the README explains the one-time connection). If you only want to rebuild locally without
# publishing, run scripts/build.py instead.

cd "$(dirname "$0")" || { echo "Could not find repo folder."; read -r; exit 1; }

# --- locate Python 3 ---
PY=""
for cand in python3 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
  if command -v "$cand" >/dev/null 2>&1 || [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
  echo "Python 3 not found. Install from https://www.python.org/downloads/ then retry."
  echo "Press Return to close."; read -r; exit 1
fi

# --- build ---
echo "Step 1/2: rebuilding dashboard..."
"$PY" scripts/build.py || { echo "Build failed - not publishing."; echo "Press Return to close."; read -r; exit 1; }

# --- publish ---
echo ""
echo "Step 2/2: publishing to GitHub..."
if ! command -v git >/dev/null 2>&1; then
  echo "git is not installed. Install Xcode command line tools with: xcode-select --install"
  echo "Press Return to close."; read -r; exit 1
fi
if [ ! -d .git ]; then
  echo "This folder isn't connected to GitHub yet. See the README ('One-time setup')."
  echo "Press Return to close."; read -r; exit 1
fi

git add docs/index.html
# Only commit if something actually changed
if git diff --cached --quiet; then
  echo "No changes to publish (dashboard already up to date)."
else
  STAMP="$(date '+%Y-%m-%d %H:%M')"
  git commit -m "Dashboard refresh $STAMP" >/dev/null
  if git push; then
    echo ""
    echo "Published. Your live link will update within ~1 minute."
  else
    echo ""
    echo "Push failed. Check your internet/login. Your local build is still updated."
  fi
fi

echo ""
echo "Press Return to close this window."
read -r
