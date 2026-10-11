#!/usr/bin/env bash
# Usage: verify_bundle_restore.sh BUNDLE  -- restores into a clean temp repo and compares refs.
set -euo pipefail
bundle=$(realpath "$1")
git bundle verify "$bundle"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
git clone --mirror "$bundle" "$tmp/restored.git" >/dev/null 2>&1
git for-each-ref --format='%(refname) %(objectname)' | grep -v '^refs/\(remotes\|pull\)/' | sort > "$tmp/src"
git --git-dir="$tmp/restored.git" for-each-ref --format='%(refname) %(objectname)' | sort > "$tmp/dst"
missing=$(comm -23 "$tmp/src" "$tmp/dst" || true)
if [ -n "$missing" ]; then echo "Refs missing from restore:"; echo "$missing"; exit 1; fi
git --git-dir="$tmp/restored.git" fsck --no-progress
echo "Bundle restore verified: $(wc -l < "$tmp/dst") refs"
