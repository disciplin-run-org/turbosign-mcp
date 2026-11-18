#!/usr/bin/env bash
# release.sh - cut a turbosign-mcp release: run the suite at the commit that
# ships and, only when it is green, push that commit and its version tag. CI
# is this script, not a GitHub Actions workflow.
#
# Jesper, 2026-11-18 (QM #1608): "We will have CI but it will be as part of
# release and deploy scripts, it will not be in GitHub actions." The contract
# is jjstack references/release-ci.md (QM #1601).
#
# Usage: scripts/release.sh [--dir DIR] [--suite CMD] [--remote NAME] [--branch NAME] [--dry-run]
#
#   --dir DIR      the clone to release (default: the current directory)
#   --suite CMD    the suite, one shell command run with `bash -eo pipefail`
#                  from DIR with no input (default: bash scripts/suite.sh)
#   --remote NAME  default origin
#   --branch NAME  the branch releases come from (default main)
#   --dry-run      run every check and the suite, then undo the release
#                  commit and say what it would release
#
# In order, and it stops at the first that fails:
#   1. DIR is a clean checkout whose HEAD is the remote branch's tip, read
#      fresh, and the remote pushes to the URL it fetches from.
#   2. The version, named by jjstack's bin/jjstack-release-version (found at
#      $JJSTACK_RELEASE_VERSION, on PATH, or in ~/.claude/skills/jjstack/bin).
#      No output means nothing to release: the suite does not run.
#   3. A commit "chore(release): vX.Y.Z" writes VERSION and pyproject.toml.
#      The server reports VERSION at runtime (--version, --selftest), so the
#      version files ship in the released commit itself. This is the one
#      deviation from release-ci.md step 5 ("push only the tag"), the same
#      one leanspecs and iris-qa make.
#   4. The suite runs at that commit in its own process group, within
#      TURBOSIGN_RELEASE_SUITE_TIMEOUT_S seconds (default 1800). Red or past
#      the limit: the commit is undone, nothing tagged.
#   5. HEAD, the tree and the remote branch are read again. A suite that moved
#      HEAD or left a changed or untracked file (named), or a remote that
#      moved: refused.
#   6. An annotated tag records the run (suite, its last line as the totals,
#      commit, UTC time, and the interpreter when the suite names one), and
#      the commit and the tag go up in one atomic push, bounded by
#      TURBOSIGN_RELEASE_PUSH_TIMEOUT_S seconds (default 300).
#
# Interruption: INT, TERM or HUP from the release commit until tagging starts
# stops the suite's whole process group, deletes any local tag, resets main to
# where it was and restores VERSION and pyproject.toml. From tagging on, the
# three signals are ignored, so a release is never left half-done. A push that
# fails or passes its limit is followed by a read of the remote, bounded by
# TURBOSIGN_RELEASE_READBACK_TIMEOUT_S (default 60): if it holds commit and
# tag, that is the release; if it holds neither (its branch still at the base,
# or moved on by someone else), the local tag is deleted and main reset; if it
# cannot be read, or holds the tag on another commit, both are kept and the
# script prints how to finish by hand.
#
# Cite the run with: git tag -l --format='%(contents)' vX.Y.Z
# The whole suite output is kept in
# ${TURBOSIGN_RELEASE_LOG_DIR:-~/.jjstack/releases/turbosign-mcp}/<tag>-<sha12>.log,
# where <sha12> is the release commit the suite ran at.
#
# Exit: 0 released, nothing to release, or a dry run passed; 1 refused (the
# reason is printed); 2 usage, not a repository, no version tool, or a log it
# cannot write; 129, 130 or 143 interrupted by HUP, INT or TERM.
set -uo pipefail

dir=. suite="bash scripts/suite.sh" remote=origin branch=main dry=0
need() { [ "$2" -ge 2 ] || { echo "release.sh: $1 needs a value" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dir)     need "$1" $#; dir="$2"; shift 2 ;;
    --suite)   need "$1" $#; suite="$2"; shift 2 ;;
    --remote)  need "$1" $#; remote="$2"; shift 2 ;;
    --branch)  need "$1" $#; branch="$2"; shift 2 ;;
    --dry-run) dry=1; shift ;;
    -h|--help) awk 'NR == 1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "release.sh: unknown argument: $1" >&2; exit 2 ;;
  esac
done

g() { git -C "$dir" "$@"; }
base="" suite_pid="" new=""
files_of() { cut -c4- <<<"$1" | head -n 10 | paste -sd' ' -; }

undo() {
  # Put main back where it was and restore only the two files the release
  # commit wrote. A soft reset keeps any other edit made while the suite ran.
  [ -n "$base" ] || return 0
  if [ -n "$new" ] && g rev-parse -q --verify "refs/tags/$new" >/dev/null; then
    g tag -d "$new" >/dev/null 2>&1
  fi
  g reset -q --soft "$base"
  g restore -q --source="$base" --staged --worktree -- VERSION pyproject.toml 2>/dev/null \
    || g restore -q --source="$base" --staged --worktree -- VERSION
  base=""
}
refuse() { undo; echo "release.sh: refused: $*" >&2; exit 1; }

stop_suite() {
  # The suite leads its own process group (setsid), so one kill reaches every
  # process it started. timeout -k sends KILL to the group 10 s after a TERM
  # that is ignored; the last KILL takes whatever is still in the group.
  [ -n "$suite_pid" ] || return 0
  kill -TERM -- "-$suite_pid" 2>/dev/null
  wait "$suite_pid" 2>/dev/null
  kill -KILL -- "-$suite_pid" 2>/dev/null
  suite_pid=""
}
kill_tree() {
  # KILL a process and every descendant, children first: once a parent is
  # gone its children are reparented and can no longer be found from it.
  local kid
  for kid in $(pgrep -P "$1"); do kill_tree "$kid"; done
  kill -KILL "$1" 2>/dev/null
}
bounded() {
  # Run a command within a time limit, in this shell's own process group, so
  # it keeps the operator's terminal (a credential or passphrase prompt reads
  # /dev/tty) and the signals this shell ignores. Past the limit, the whole
  # tree is killed and the exit is 137.
  local limit="$1" pid watch rc
  shift
  "$@" &
  pid=$!
  ( end=$((SECONDS + limit))
    while kill -0 "$pid" 2>/dev/null; do
      if [ "$SECONDS" -ge "$end" ]; then kill_tree "$pid"; exit 0; fi
      sleep 0.2
    done ) &
  watch=$!
  wait "$pid"
  rc=$?
  wait "$watch"
  return "$rc"
}
on_signal() {
  trap '' INT TERM HUP
  stop_suite
  undo
  echo "release.sh: interrupted by SIG$1; nothing released, main restored" >&2
  exit "$2"
}

top="$(g rev-parse --show-toplevel 2>/dev/null)" || { echo "release.sh: $dir is not a git repository" >&2; exit 2; }
dir="$top"

relver="${JJSTACK_RELEASE_VERSION:-}"
if [ -z "$relver" ]; then
  relver="$(command -v jjstack-release-version || true)"
  [ -n "$relver" ] || relver="$HOME/.claude/skills/jjstack/bin/jjstack-release-version"
fi
[ -x "$relver" ] || { echo "release.sh: jjstack-release-version not found at $relver; install jjstack or set JJSTACK_RELEASE_VERSION" >&2; exit 2; }

# 1. A clean checkout of the remote branch's tip, fetched from where it pushes.
dirty="$(g status --porcelain --untracked-files=all)"
[ -z "$dirty" ] || refuse "the tree has changes or untracked files ($(files_of "$dirty")); release a clean checkout"
fetch_url="$(g remote get-url "$remote" 2>/dev/null)" || refuse "no remote named $remote"
push_urls="$(g remote get-url --all --push "$remote" 2>/dev/null)" || refuse "no remote named $remote"
# Name the remote, never its URLs: a URL can carry a credential.
[ "$push_urls" = "$fetch_url" ] \
  || refuse "$remote's push URL differs from its fetch URL; use a remote whose fetch and push URL are the one repository"
remote_tip() { g ls-remote "$remote" "refs/heads/$branch" | cut -f1; }
g fetch -q --tags "$remote" "refs/heads/$branch:refs/remotes/$remote/$branch" \
  || refuse "could not fetch $remote/$branch"
sha="$(g rev-parse HEAD)"
tip="$(remote_tip)"
[ -n "$tip" ] || refuse "$remote has no branch $branch"
[ "$sha" = "$tip" ] || refuse "HEAD ($sha) is not $remote/$branch's tip ($tip); a release is $branch's own commit"

# 2. The version, from jjstack's own rule. Nothing is written yet, so these
#    refusals have nothing to undo.
new="$("$relver" "$dir")" || refuse "jjstack-release-version ($relver) failed at $sha"
if [ -z "$new" ]; then
  echo "nothing to release at $sha: no feat, fix or breaking change since the last release"
  exit 0
fi
grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+$' <<<"$new" \
  || refuse "jjstack-release-version printed '$new', not vX.Y.Z"
! g rev-parse -q --verify "refs/tags/$new" >/dev/null \
  || refuse "tag $new already exists; nothing tagged"
version="${new#v}"

logdir="${TURBOSIGN_RELEASE_LOG_DIR:-$HOME/.jjstack/releases/turbosign-mcp}"

# 3. The release commit, carrying the version files. The traps are set before
#    the first write, so a signal from here on always restores main.
base="$sha"
trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'on_signal HUP 129' HUP
printf '%s\n' "$version" >"$dir/VERSION"
if [ -f "$dir/pyproject.toml" ]; then
  sed -i "0,/^version = \".*\"/s//version = \"$version\"/" "$dir/pyproject.toml"
  grep -qx "version = \"$version\"" "$dir/pyproject.toml" \
    || refuse "could not set version = \"$version\" in pyproject.toml; its version line is not version = \"X.Y.Z\""
  g add VERSION pyproject.toml || refuse "could not stage the version files"
else
  g add VERSION || refuse "could not stage VERSION"
fi
g commit -q --no-verify -m "chore(release): $new" || refuse "could not commit the version files"
rel="$(g rev-parse HEAD)"

log="$logdir/$new-${rel:0:12}.log"
# The log is private to the operator and never written through a symlink. A
# log it cannot write is its own failure, never reported as a red suite.
if [ -L "$log" ] || ! (umask 077 && mkdir -p "$logdir" && : >"$log") 2>/dev/null; then
  undo
  echo "release.sh: cannot write the suite log at $log; set TURBOSIGN_RELEASE_LOG_DIR" >&2
  exit 2
fi

# 4. The suite, at the release commit. -e and pipefail: a failing command
#    anywhere in it is red, even when a later command prints a passing line.
#    It runs in the background in its own process group, so a signal reaches
#    the trap at once (bash defers traps while a foreground child runs) and the
#    trap can stop the whole group.
limit="${TURBOSIGN_RELEASE_SUITE_TIMEOUT_S:-1800}"
echo "running the suite at $rel for $new (limit ${limit}s): $suite"
( cd "$dir" && exec setsid timeout -k 10 "$limit" bash -eo pipefail -c "$suite" ) </dev/null >>"$log" 2>&1 &
suite_pid=$!
wait "$suite_pid"
suite_rc=$?
suite_pid=""
totals="$(grep -v '^[[:space:]]*$' "$log" | tail -n1)"
if [ "$suite_rc" -ne 0 ]; then
  tail -n 20 "$log" | sed 's/^/    /' >&2
  refuse "the suite is red at $rel (exit $suite_rc); nothing tagged. Whole output: $log"
fi
echo "suite green: ${totals:-<no output>}"

# 5. Nothing moved while it ran.
[ "$(g rev-parse HEAD)" = "$rel" ] || refuse "the suite moved HEAD away from $rel; nothing tagged"
left="$(g status --porcelain --untracked-files=all)"
[ -z "$left" ] || refuse "the suite left changed or untracked files in the checkout ($(files_of "$left")); nothing tagged"
now="$(remote_tip)"
[ "$now" = "$base" ] || refuse "$remote/$branch moved from $base to $now while the suite ran; run the release again from the new tip"

if [ "$dry" -eq 1 ]; then
  undo
  trap - INT TERM HUP
  echo "dry run: would release $new on top of $sha (suite: $suite; result: ${totals:-<no output>})"
  exit 0
fi

# 6. The tag, carrying the record; commit and tag pushed atomically. The three
#    signals are ignored from here, so an interrupt can never leave a tag
#    without its push or a push without its local record. git and its
#    helpers inherit the ignore, and they keep the operator's terminal, so a
#    credential or passphrase prompt still works. The push is bounded by
#    TURBOSIGN_RELEASE_PUSH_TIMEOUT_S (default 300): a stalled push is
#    killed, and origin is then read to see what it holds.
trap '' INT TERM HUP
msg="$(printf '%s\n\nsuite: %s\nresult: %s\ncommit: %s\nran: %s\n' \
  "$new" "$suite" "${totals:-<no output>}" "$rel" "$(date -u +%Y-%m-%dT%H:%M:%SZ)")"
# scripts/suite.sh names its interpreter on a "python: X.Y.Z" line.
interp="$(grep -m1 -E '^python: [0-9]' "$log" | cut -d' ' -f2-)"
[ -z "$interp" ] || msg="$(printf '%s\ninterpreter: %s\n' "$msg" "$interp")"
g tag -a "$new" -m "$msg" "$rel" || refuse "could not create tag $new"
push_limit="${TURBOSIGN_RELEASE_PUSH_TIMEOUT_S:-300}"
readback_limit="${TURBOSIGN_RELEASE_READBACK_TIMEOUT_S:-60}"
bounded "$push_limit" \
  git -C "$dir" push -q --atomic "$remote" "$rel:refs/heads/$branch" "refs/tags/$new"
push_rc=$?
if [ "$push_rc" -ne 0 ]; then
  why="the push failed (exit $push_rc)"
  [ "$push_rc" -ne 137 ] || why="the push timed out after ${push_limit}s"
  echo "release.sh: $why; reading $remote to see what it holds" >&2
  # --atomic: origin holds both refs or neither. The read is bounded too.
  held="$(bounded "$readback_limit" git -C "$dir" ls-remote "$remote" \
            "refs/heads/$branch" "refs/tags/$new")"
  ls_rc=$?
  held_main="$(awk -v r="refs/heads/$branch" '$2 == r {print $1}' <<<"$held")"
  held_tag="$(awk -v r="refs/tags/$new" '$2 == r {print $1}' <<<"$held")"
  if [ "$ls_rc" -eq 0 ] && [ "$held_main" = "$rel" ] && [ -n "$held_tag" ]; then
    echo "release.sh: $remote holds $rel and $new: the release went through" >&2
  elif [ "$ls_rc" -eq 0 ] && [ -z "$held_tag" ] && [ "$held_main" = "$base" ]; then
    refuse "could not push $new to $remote: $why, and $remote holds neither; the local tag and release commit were removed"
  elif [ "$ls_rc" -eq 0 ] && [ -z "$held_tag" ] && [ "$held_main" != "$rel" ]; then
    refuse "could not push $new to $remote: $why; $remote moved to ${held_main:-<no $branch>} while the release was pushing, so the local tag and release commit were removed. Run the release again from the new tip"
  else
    # Origin cannot be read, or holds a state the release did not make (its
    # tag on another commit): keep the local record, never guess.
    trap - INT TERM HUP
    if [ "$ls_rc" -ne 0 ]; then
      echo "release.sh: refused: $why, and $remote could not be read back (ls-remote exit $ls_rc)." >&2
    else
      echo "release.sh: refused: $why, and $remote holds $branch at ${held_main:-<none>} with $new at ${held_tag:-<none>}, which this release did not make." >&2
    fi
    echo "  The release commit $rel and tag $new are kept in $dir." >&2
    printf '  If %s has %s at %s: nothing to do. If not: git -C %q reset --soft %s && git -C %q restore --staged --worktree --source=%s -- VERSION pyproject.toml && git -C %q tag -d %s\n' \
      "$remote" "$new" "$rel" "$dir" "$base" "$dir" "$base" "$dir" "$new" >&2
    exit 1
  fi
fi
base=""
trap - INT TERM HUP
echo "released $new at $rel: ${totals:-<no output>}"
echo "cite the run with: git tag -l --format='%(contents)' $new"
