#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

repo=$(git rev-parse --show-toplevel 2>/dev/null) || fail "not inside a Git repository"
repo=$(cd "$repo" && pwd -P)

current_branch=$(git -C "$repo" branch --show-current)
[[ "$current_branch" == "main" ]] || fail "current branch must be main (got: ${current_branch:-detached})"

local_branches=$(git -C "$repo" branch --format='%(refname:short)')
[[ "$local_branches" == "main" ]] || fail "local branches must be exactly [main]"

tracking_branches=$(git -C "$repo" for-each-ref --format='%(refname:short)' refs/remotes)
[[ "$tracking_branches" == "origin/main" ]] || fail "remote-tracking branches must be exactly [origin/main]"

mapfile_compat=()
while IFS= read -r line; do
  [[ "$line" == worktree\ * ]] && mapfile_compat+=("${line#worktree }")
done < <(git -C "$repo" -c core.quotePath=false worktree list --porcelain)
[[ ${#mapfile_compat[@]} -eq 1 ]] || fail "exactly one worktree must exist"
worktree=$(cd "${mapfile_compat[0]}" && pwd -P)
[[ "$worktree" == "$repo" ]] || fail "the sole worktree must be the canonical repository root"

[[ -z "$(git -C "$repo" status --porcelain=v1 --untracked-files=all)" ]] || fail "working tree must be clean"

main_sha=$(git -C "$repo" rev-parse main)
tracking_sha=$(git -C "$repo" rev-parse origin/main)
[[ "$main_sha" == "$tracking_sha" ]] || fail "main and origin/main must have the same SHA"

remote_heads=$(git -C "$repo" ls-remote --heads origin)
[[ $(printf '%s\n' "$remote_heads" | awk 'NF { count++ } END { print count + 0 }') -eq 1 ]] || fail "origin must expose exactly one branch"
remote_sha=$(printf '%s\n' "$remote_heads" | awk '$2 == "refs/heads/main" { print $1 }')
[[ -n "$remote_sha" ]] || fail "the sole remote branch must be main"
[[ "$main_sha" == "$remote_sha" ]] || fail "main, origin/main, and GitHub main must have the same SHA"

common_git_dir=$(git -C "$repo" rev-parse --git-common-dir)
if [[ "$common_git_dir" != /* ]]; then
  common_git_dir="$repo/$common_git_dir"
fi
[[ ! -e "$common_git_dir/spacetime-uow.json" ]] || fail "no active UOW lease may exist"

echo "PASS: canonical trunk state"
