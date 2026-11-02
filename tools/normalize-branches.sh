#!/usr/bin/env bash
# Normalize the remote GitHub branch policy to exactly master + dev.
# Requires gh CLI authenticated as a repository administrator; NEVER run on hosts.
set -Eeuo pipefail
REPO=bradjtrammell/rivendell-complete
usage(){
  cat <<'HELP'
Usage: bash tools/normalize-branches.sh [--check|--apply]
  --check  Verify branch ancestry, report current remote state (default).
  --apply  Set master as GitHub default, delete stale v4 and feat/ branches
           ONLY after ensuring all their work is preserved by master/dev.

Run from an authenticated MAINTAINER workstation (gh auth login).
This script does not need or store credentials on broadcast servers.
HELP
}
mode=check
if (($#)); then
  [[ "$#" -eq 1 ]] || { usage >&2; exit 2; }
  case "$1" in
    --check) ;;
    --apply) mode=apply ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
fi
command -v gh >/dev/null || { echo 'Install GitHub CLI (gh)' >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo 'Log into gh on this workstation' >&2; exit 1; }
read_ref(){
  gh api "repos/$REPO/git/ref/heads/$1" --jq '.object.sha'
}
master="$(read_ref master)"
dev="$(read_ref dev)"
upstream="$(read_ref v4)"
old="$(read_ref feat/ubuntu26-external-nas-media)"
[[ -n "$master" && -n "$dev" && -n "$upstream" && -n "$old" ]] ||
  { echo 'Cannot resolve all four expected remote branches' >&2; exit 1; }
[[ "$master" == "$upstream" ]] ||
  { echo 'v4 has unique commits; refusing deletion' >&2; exit 1; }
behind="$(gh api "repos/$REPO/compare/$old...$dev" --jq '.behind_by')"
[[ "$behind" == 0 ]] ||
  { echo 'Old feature branch has commits missing from dev; refusing deletion' >&2; exit 1; }
default="$(gh api "repos/$REPO" --jq '.default_branch')"
[[ "$default" == v4 || "$default" == master ]] ||
  { echo "Unexpected default branch: $default" >&2; exit 1; }
printf 'master (upstream): %s\ndev (Complete 5.0): %s\nv4 (redundant): %s\nold feature (merged ancestry): %s\nCurrent default: %s\n' \
  "$master" "$dev" "$upstream" "$old" "$default"
if [[ "$mode" == check ]]; then
  echo 'Check only; run --apply to normalize remote repository branches.'
  exit 0
fi
echo 'Setting master as remote GitHub default'
gh api --method PATCH "repos/$REPO" -f default_branch=master >/dev/null
[[ "$(gh api "repos/$REPO" --jq '.default_branch')" == master ]] ||
  { echo 'Could not verify new default; no branches deleted' >&2; exit 1; }
echo 'Removing safely superseded v4 branch'
gh api --method DELETE "repos/$REPO/git/refs/heads/v4" >/dev/null
echo 'Removing safely superseded feature branch'
gh api --method DELETE \
  "repos/$REPO/git/refs/heads/feat/ubuntu26-external-nas-media" >/dev/null
actual="$(gh api "repos/$REPO/branches?per_page=100" --jq '.[].name' | sort)"
expected="$(printf 'dev\nmaster' | sort)"
[[ "$actual" == "$expected" ]] ||
  { printf 'Unexpected remaining branches:\n%s\n' "$actual" >&2; exit 1; }
echo 'Verified exactly two remote branches: master, dev'
