#!/usr/bin/env bash
# Mirror the CI clang-format check locally.
#
# Usage:
#   scripts/check-format.sh                # check files changed vs origin/main
#   scripts/check-format.sh --all          # check every C/C++ file under main/
#   scripts/check-format.sh --fix          # apply formatting fixes in place
#   scripts/check-format.sh --base <ref>   # diff against a specific git ref
set -euo pipefail

base="origin/main"
mode="check"
scope="diff"

while [ $# -gt 0 ]; do
  case "$1" in
    --all) scope="all"; shift ;;
    --fix) mode="fix"; shift ;;
    --base) base="${2:?missing ref}"; shift 2 ;;
    -h|--help)
      sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if ! command -v clang-format >/dev/null 2>&1; then
  echo "clang-format not found. Install clang-format-18 (or newer)." >&2
  exit 1
fi

cd "$(git rev-parse --show-toplevel)"

if [ "$scope" = "all" ]; then
  mapfile -t files < <(
    git ls-files 'main/*.c' 'main/*.cc' 'main/*.cpp' 'main/*.h' 'main/*.hpp' \
                 'main/**/*.c' 'main/**/*.cc' 'main/**/*.cpp' 'main/**/*.h' 'main/**/*.hpp' \
      | grep -Ev '^main/(boards/[^/]+/third_party|managed_components|build)/' || true
  )
else
  if ! git rev-parse --verify "$base" >/dev/null 2>&1; then
    echo "warn: $base not found, falling back to HEAD~1" >&2
    base="HEAD~1"
  fi
  mapfile -t files < <(
    git diff --name-only --diff-filter=ACMRT "$base" -- \
      'main/*.c' 'main/*.cc' 'main/*.cpp' 'main/*.h' 'main/*.hpp' \
      'main/**/*.c' 'main/**/*.cc' 'main/**/*.cpp' 'main/**/*.h' 'main/**/*.hpp' \
      | grep -Ev '^main/(boards/[^/]+/third_party|managed_components|build)/' || true
  )
fi

if [ "${#files[@]}" -eq 0 ]; then
  echo "no C/C++ files to check"
  exit 0
fi

status=0
for f in "${files[@]}"; do
  [ -z "$f" ] && continue
  [ -f "$f" ] || continue
  if [ "$mode" = "fix" ]; then
    clang-format -i --style=file "$f"
  else
    clang-format --style=file --dry-run --Werror "$f" || status=1
  fi
done

if [ "$mode" = "check" ] && [ "$status" -ne 0 ]; then
  echo
  echo "Format violations detected. Re-run with --fix to apply changes."
  exit 1
fi
