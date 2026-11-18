"""scripts/release.sh: the suite runs at the commit that ships, and only a
green run is tagged and pushed. CI is that script, not GitHub Actions.

Every test builds a throwaway bare ``origin`` and a clone of it, so nothing
here touches the real remote. Git runs with an isolated global config, so the
operator's own hooks and signing settings cannot change the outcome.

The contract is jjstack ``references/release-ci.md`` (QM #1601); the version
comes from jjstack's ``bin/jjstack-release-version``, never from logic of our
own.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release.sh"
SUITE_SCRIPT = ROOT / "scripts" / "suite.sh"
DEFAULT_RELVER = Path.home() / ".claude/skills/jjstack/bin/jjstack-release-version"


def _relver() -> str:
    """The real jjstack version tool. Missing is a failure, never a skip."""
    path = Path(os.environ.get("JJSTACK_RELEASE_VERSION", DEFAULT_RELVER))
    assert path.is_file(), (
        f"jjstack-release-version not found at {path}; install jjstack or set "
        "JJSTACK_RELEASE_VERSION"
    )
    return str(path)
# end def


@pytest.fixture
def env(tmp_path):
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text(
        "[user]\n\tname = Release Test\n\temail = release@example.invalid\n"
        "[init]\n\tdefaultBranch = main\n"
    )
    e = dict(os.environ)
    e.update(
        GIT_CONFIG_GLOBAL=str(gitconfig),
        GIT_CONFIG_NOSYSTEM="1",
        TURBOSIGN_RELEASE_LOG_DIR=str(tmp_path / "logs"),
        JJSTACK_RELEASE_VERSION=_relver(),
    )
    return e
# end def


def git(cwd, *args, env, check=True) -> str:
    r = subprocess.run(
        ["git", "-C", str(cwd), *args],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed: {r.stderr}")
    # end if
    return r.stdout.strip()
# end def


@pytest.fixture
def repo(tmp_path, env):
    """origin (bare) with v1.2.0 tagged and one feat after it; a clean clone."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], env=env, check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(seed)], env=env, check=True)
    (seed / "VERSION").write_text("1.2.0\n")
    (seed / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.2.0"\n'
    )
    (seed / "README.md").write_text("demo\n")
    git(seed, "add", ".", env=env)
    git(seed, "commit", "-q", "-m", "feat: initial", env=env)
    git(seed, "tag", "-a", "v1.2.0", "-m", "v1.2.0", env=env)
    (seed / "a.txt").write_text("a\n")
    git(seed, "add", ".", env=env)
    git(seed, "commit", "-q", "-m", "feat: add a", env=env)
    git(seed, "remote", "add", "origin", str(origin), env=env)
    git(seed, "push", "-q", "origin", "main", "--tags", env=env)
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], env=env, check=True)
    return {"origin": origin, "seed": seed, "clone": clone}
# end def


def release(repo, env, suite="echo '3 passed in 0.01s'", *extra, timeout=60):
    return subprocess.run(
        ["bash", str(SCRIPT), "--dir", str(repo["clone"]), "--suite", suite, *extra],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
# end def


def origin_tags(repo, env) -> str:
    return git(repo["origin"], "tag", "--list", env=env)
# end def


def origin_main(repo, env) -> str:
    return git(repo["origin"], "rev-parse", "main", env=env)
# end def


def assert_untouched(repo, env, base):
    """Nothing released: no new tag anywhere, main back where it was."""
    clone = repo["clone"]
    assert git(clone, "tag", "--list", env=env) == "v1.2.0"
    assert origin_tags(repo, env) == "v1.2.0"
    assert origin_main(repo, env) == base
    assert git(clone, "rev-parse", "HEAD", env=env) == base
    assert git(clone, "rev-parse", "main", env=env) == base
    assert (clone / "VERSION").read_text() == "1.2.0\n"
    assert 'version = "1.2.0"' in (clone / "pyproject.toml").read_text()
    assert git(clone, "status", "--porcelain", env=env) == ""
# end def


# --- the happy path ---------------------------------------------------------


def test_green_suite_releases_commit_and_annotated_tag(repo, env):
    base = origin_main(repo, env)
    r = release(repo, env)
    assert r.returncode == 0, r.stderr
    clone = repo["clone"]
    rel = git(clone, "rev-parse", "HEAD", env=env)
    assert git(clone, "rev-parse", "HEAD~1", env=env) == base
    assert git(clone, "log", "-1", "--format=%s", env=env) == "chore(release): v1.3.0"
    assert (clone / "VERSION").read_text() == "1.3.0\n"
    assert 'version = "1.3.0"' in (clone / "pyproject.toml").read_text()
    assert origin_main(repo, env) == rel
    assert "v1.3.0" in origin_tags(repo, env).split()
    assert git(repo["origin"], "cat-file", "-t", "v1.3.0", env=env) == "tag"
    record = git(repo["origin"], "tag", "-l", "--format=%(contents)", "v1.3.0", env=env)
    assert "suite: echo '3 passed in 0.01s'" in record
    assert "result: 3 passed in 0.01s" in record
    assert f"commit: {rel}" in record
    assert "ran: 20" in record
    log = Path(env["TURBOSIGN_RELEASE_LOG_DIR"]) / f"v1.3.0-{rel[:12]}.log"
    # The log is named after the commit the suite ran at: the release commit.
    assert log.read_text().strip() == "3 passed in 0.01s"
    assert oct(log.stat().st_mode & 0o777) == "0o600"
# end def


def test_the_tag_records_the_interpreter_the_suite_ran_on(repo, env):
    # One interpreter now, not a matrix: the tag says which one.
    r = release(repo, env, "echo 'python: 3.12.3'; echo '3 passed'")
    assert r.returncode == 0, r.stderr
    record = git(repo["origin"], "tag", "-l", "--format=%(contents)", "v1.3.0", env=env)
    assert "interpreter: 3.12.3" in record
    assert "result: 3 passed" in record
# end def


def test_suite_sh_names_its_interpreter_first():
    text = SUITE_SCRIPT.read_text()
    assert "print('python:', platform.python_version())" in text
# end def


def test_the_version_comes_from_jjstack_release_version(repo, env, tmp_path):
    fake = tmp_path / "relver"
    fake.write_text('#!/usr/bin/env bash\necho "called with $1" >&2\necho v7.8.9\n')
    fake.chmod(0o755)
    env["JJSTACK_RELEASE_VERSION"] = str(fake)
    r = release(repo, env)
    assert r.returncode == 0, r.stderr
    assert f"called with {repo['clone']}" in r.stderr
    assert "v7.8.9" in origin_tags(repo, env).split()
    assert (repo["clone"] / "VERSION").read_text() == "7.8.9\n"
# end def


def test_a_failing_version_tool_is_refused(repo, env, tmp_path):
    base = origin_main(repo, env)
    fake = tmp_path / "relver"
    fake.write_text("#!/usr/bin/env bash\nexit 3\n")
    fake.chmod(0o755)
    env["JJSTACK_RELEASE_VERSION"] = str(fake)
    marker = tmp_path / "ran"
    r = release(repo, env, f"touch {marker}")
    assert r.returncode == 1
    assert "jjstack-release-version" in r.stderr
    assert not marker.exists()
    assert_untouched(repo, env, base)
# end def


def test_a_missing_version_tool_is_a_usage_error(repo, env, tmp_path):
    env["JJSTACK_RELEASE_VERSION"] = str(tmp_path / "nope")
    r = release(repo, env)
    assert r.returncode == 2
    assert "jjstack-release-version" in r.stderr
# end def


def test_nothing_to_release_runs_no_suite_and_tags_nothing(repo, env, tmp_path):
    seed = repo["seed"]
    git(seed, "tag", "-a", "v1.3.0", "-m", "v1.3.0", env=env)
    (seed / "b.txt").write_text("b\n")
    git(seed, "add", ".", env=env)
    git(seed, "commit", "-q", "-m", "chore: tidy", env=env)
    git(seed, "push", "-q", "origin", "main", "--tags", env=env)
    git(repo["clone"], "pull", "-q", env=env)
    marker = tmp_path / "ran"
    r = release(repo, env, f"touch {marker}")
    assert r.returncode == 0, r.stderr
    assert "nothing to release" in r.stdout
    assert not marker.exists()
    assert sorted(origin_tags(repo, env).split()) == ["v1.2.0", "v1.3.0"]
# end def


def test_dry_run_runs_the_suite_and_releases_nothing(repo, env, tmp_path):
    base = origin_main(repo, env)
    marker = tmp_path / "ran"
    r = release(repo, env, f"touch {marker}; echo '1 passed'", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert marker.exists()
    assert "would release v1.3.0" in r.stdout
    assert_untouched(repo, env, base)
# end def


# --- refusals before anything is written -----------------------------------


def test_a_dirty_tree_is_refused_and_names_the_file(repo, env, tmp_path):
    (repo["clone"] / "stray.txt").write_text("x\n")
    marker = tmp_path / "ran"
    r = release(repo, env, f"touch {marker}")
    assert r.returncode == 1
    assert "stray.txt" in r.stderr
    assert not marker.exists()
# end def


def test_head_that_is_not_the_remote_tip_is_refused(repo, env, tmp_path):
    clone = repo["clone"]
    git(clone, "checkout", "-q", "HEAD~1", env=env)
    marker = tmp_path / "ran"
    r = release(repo, env, f"touch {marker}")
    assert r.returncode == 1
    assert "is not origin/main's tip" in r.stderr
    assert not marker.exists()
# end def


def test_push_url_that_differs_from_fetch_url_is_refused(repo, env, tmp_path):
    clone = repo["clone"]
    git(clone, "remote", "set-url", "--push", "origin", str(tmp_path / "elsewhere.git"), env=env)
    marker = tmp_path / "ran"
    r = release(repo, env, f"touch {marker}")
    assert r.returncode == 1
    assert "push URL differs from its fetch URL" in r.stderr
    assert not marker.exists()
# end def


# --- a red or misbehaving suite --------------------------------------------


def test_red_suite_tags_nothing_and_restores_main(repo, env):
    base = origin_main(repo, env)
    r = release(repo, env, "echo '1 failed, 2 passed'; exit 1")
    assert r.returncode == 1
    assert "the suite is red" in r.stderr
    assert "1 failed, 2 passed" in r.stderr
    assert_untouched(repo, env, base)
# end def


def test_a_failing_command_early_in_the_suite_is_red(repo, env):
    # -e and pipefail: a later passing line does not hide an earlier failure.
    base = origin_main(repo, env)
    r = release(repo, env, "false; echo '3 passed'")
    assert r.returncode == 1
    assert_untouched(repo, env, base)
# end def


def test_red_suite_keeps_a_tracked_edit_made_while_it_ran(repo, env):
    base = origin_main(repo, env)
    readme = repo["clone"] / "README.md"
    r = release(repo, env, f"echo edited >> {readme}; exit 1")
    assert r.returncode == 1
    assert readme.read_text() == "demo\nedited\n"
    assert git(repo["clone"], "rev-parse", "HEAD", env=env) == base
    assert (repo["clone"] / "VERSION").read_text() == "1.2.0\n"
    assert origin_tags(repo, env) == "v1.2.0"
# end def


def test_suite_that_leaves_a_file_is_refused_and_names_it(repo, env):
    base = origin_main(repo, env)
    r = release(repo, env, "touch left-behind.txt; echo '1 passed'")
    assert r.returncode == 1
    assert "left-behind.txt" in r.stderr
    assert origin_tags(repo, env) == "v1.2.0"
    assert origin_main(repo, env) == base
    assert git(repo["clone"], "rev-parse", "HEAD", env=env) == base
# end def


def test_suite_past_its_time_limit_is_red(repo, env):
    base = origin_main(repo, env)
    env["TURBOSIGN_RELEASE_SUITE_TIMEOUT_S"] = "1"
    started = time.monotonic()
    r = release(repo, env, "sleep 30")
    assert time.monotonic() - started < 20
    assert r.returncode == 1
    assert "the suite is red" in r.stderr
    assert_untouched(repo, env, base)
# end def


def test_remote_that_moves_while_the_suite_runs_is_refused(repo, env):
    base = origin_main(repo, env)
    seed = repo["seed"]
    (seed / "c.txt").write_text("c\n")
    git(seed, "add", ".", env=env)
    git(seed, "commit", "-q", "-m", "fix: c", env=env)
    moved = git(seed, "rev-parse", "HEAD", env=env)
    suite = (
        f"GIT_CONFIG_GLOBAL={env['GIT_CONFIG_GLOBAL']} "
        f"git -C {seed} push -q origin main; echo '1 passed'"
    )
    r = release(repo, env, suite)
    assert r.returncode == 1
    assert "moved" in r.stderr and "while the suite ran" in r.stderr
    assert origin_main(repo, env) == moved
    assert origin_tags(repo, env) == "v1.2.0"
    assert git(repo["clone"], "rev-parse", "HEAD", env=env) == base
# end def


# --- interruption ------------------------------------------------------------


def _wait_for(path: Path, seconds: float = 20) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return
        # end if
        time.sleep(0.05)
    # end while
    raise AssertionError(f"{path} never appeared")
# end def


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # end try
    # A zombie still answers kill(0); it is dead for our purpose.
    stat = Path(f"/proc/{pid}/stat")
    return stat.exists() and stat.read_text().split(") ", 1)[1][0] != "Z"
# end def


@pytest.mark.parametrize(
    ("sig", "code"),
    [(signal.SIGINT, 130), (signal.SIGTERM, 143), (signal.SIGHUP, 129)],
    ids=["SIGINT", "SIGTERM", "SIGHUP"],
)
def test_a_signal_during_the_suite_stops_it_and_restores_main(repo, env, tmp_path, sig, code):
    base = origin_main(repo, env)
    pidfile = tmp_path / "grandchild.pid"
    # The suite starts a grandchild of its own: the whole process group must
    # go, not only the shell the script started.
    suite = f"sleep 300 & echo $! > {pidfile}; wait"
    proc = subprocess.Popen(
        ["bash", str(SCRIPT), "--dir", str(repo["clone"]), "--suite", suite],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for(pidfile)
    grandchild = int(pidfile.read_text())
    assert _alive(grandchild)
    proc.send_signal(sig)
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == code, err
    assert "interrupted" in err
    deadline = time.monotonic() + 10
    while _alive(grandchild) and time.monotonic() < deadline:
        time.sleep(0.05)
    # end while
    assert not _alive(grandchild), "the suite's process group was not stopped"
    assert_untouched(repo, env, base)
# end def


def test_a_grandchild_that_ignores_term_is_killed_too(repo, env, tmp_path):
    # The suite's shell dies on TERM, so timeout exits at once without its
    # kill-after; only the script's own KILL to the group reaches this one.
    base = origin_main(repo, env)
    pidfile = tmp_path / "stubborn.pid"
    suite = f"( trap '' TERM; exec sleep 300 ) & echo $! > {pidfile}; wait"
    proc = subprocess.Popen(
        ["bash", str(SCRIPT), "--dir", str(repo["clone"]), "--suite", suite],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    _wait_for(pidfile)
    stubborn = int(pidfile.read_text())
    proc.send_signal(signal.SIGTERM)
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == 143, err
    deadline = time.monotonic() + 5
    while _alive(stubborn) and time.monotonic() < deadline:
        time.sleep(0.05)
    # end while
    assert not _alive(stubborn), "a TERM-ignoring process in the suite survived"
    assert_untouched(repo, env, base)
# end def


def test_ctrl_c_at_the_terminal_restores_main(repo, env, tmp_path):
    # A terminal's Ctrl-C signals the whole foreground process group, not one
    # pid. The suite still goes, and main is still restored.
    base = origin_main(repo, env)
    pidfile = tmp_path / "child.pid"
    suite = f"sleep 300 & echo $! > {pidfile}; wait"
    proc = subprocess.Popen(
        ["bash", str(SCRIPT), "--dir", str(repo["clone"]), "--suite", suite],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    _wait_for(pidfile)
    child = int(pidfile.read_text())
    os.killpg(proc.pid, signal.SIGINT)
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == 130, err
    deadline = time.monotonic() + 10
    while _alive(child) and time.monotonic() < deadline:
        time.sleep(0.05)
    # end while
    assert not _alive(child)
    assert_untouched(repo, env, base)
# end def


def test_a_signal_once_tagging_starts_does_not_leave_it_half_done(repo, env, tmp_path):
    # A pre-push hook signals the script while the push is under way. From
    # tagging on the release is never stopped half-way: it finishes.
    pidfile = tmp_path / "release.pid"
    hook = repo["clone"] / ".git" / "hooks" / "pre-push"
    hook.write_text(
        "#!/usr/bin/env bash\n"
        f"while [ ! -s {pidfile} ]; do sleep 0.05; done\n"
        f"for s in INT TERM HUP; do kill -$s $(cat {pidfile}); done\n"
        "sleep 1\n"
        "exit 0\n"
    )
    hook.chmod(0o755)
    proc = subprocess.Popen(
        ["bash", str(SCRIPT), "--dir", str(repo["clone"]), "--suite", "echo '1 passed'"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pidfile.write_text(str(proc.pid))
    out, err = proc.communicate(timeout=60)
    assert proc.returncode == 0, err
    assert "released v1.3.0" in out
    rel = git(repo["clone"], "rev-parse", "HEAD", env=env)
    assert origin_main(repo, env) == rel
    assert "v1.3.0" in origin_tags(repo, env).split()
    assert git(repo["clone"], "tag", "--list", "v1.3.0", env=env) == "v1.3.0"
# end def


def test_a_refused_push_removes_the_local_tag_and_restores_main(repo, env):
    base = origin_main(repo, env)
    hook = repo["clone"] / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/usr/bin/env bash\nexit 1\n")
    hook.chmod(0o755)
    r = release(repo, env)
    assert r.returncode == 1
    assert "could not push" in r.stderr
    assert_untouched(repo, env, base)
# end def


def test_a_remote_that_refuses_only_the_tag_gets_neither(repo, env):
    # The update hook judges each ref on its own. Without --atomic, main would
    # move and the tag would not: a release with no record.
    base = origin_main(repo, env)
    hook = repo["origin"] / "hooks" / "update"
    hook.write_text(
        '#!/usr/bin/env bash\ncase "$1" in refs/tags/*) exit 1 ;; esac\nexit 0\n'
    )
    hook.chmod(0o755)
    r = release(repo, env)
    assert r.returncode == 1
    assert "could not push" in r.stderr
    assert_untouched(repo, env, base)
# end def


def _stall_origin(repo, hook_name: str, then: str) -> None:
    """Make origin's hook sleep, then exit with `then`."""
    hook = repo["origin"] / "hooks" / hook_name
    hook.write_text(f"#!/usr/bin/env bash\nsleep 30\nexit {then}\n")
    hook.chmod(0o755)
# end def


def test_a_stalled_push_is_bounded_and_restores_main(repo, env):
    # The remote never answers within the limit and in the end refuses.
    base = origin_main(repo, env)
    _stall_origin(repo, "pre-receive", "1")
    env["TURBOSIGN_RELEASE_PUSH_TIMEOUT_S"] = "2"
    started = time.monotonic()
    r = release(repo, env, timeout=60)
    assert time.monotonic() - started < 25, "the push was not bounded"
    assert r.returncode == 1
    assert "timed out" in r.stderr
    assert_untouched(repo, env, base)
# end def


def test_signals_during_a_stalled_push_are_ignored_but_the_limit_holds(repo, env, tmp_path):
    base = origin_main(repo, env)
    _stall_origin(repo, "pre-receive", "1")
    env["TURBOSIGN_RELEASE_PUSH_TIMEOUT_S"] = "3"
    proc = subprocess.Popen(
        ["bash", str(SCRIPT), "--dir", str(repo["clone"]), "--suite", "echo '1 passed'"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    # Wait until the push is running, then send what a terminal would.
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if git(repo["clone"], "tag", "--list", "v1.3.0", env=env) == "v1.3.0":
            break
        # end if
        time.sleep(0.05)
    # end while
    time.sleep(0.3)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        os.killpg(proc.pid, sig)
    # end for
    _, err = proc.communicate(timeout=60)
    assert proc.returncode == 1, err
    assert "timed out" in err
    assert_untouched(repo, env, base)
# end def


def test_a_push_that_times_out_after_the_remote_took_it_is_a_release(repo, env):
    # post-receive runs after the refs are updated and the client waits for
    # it: the push times out although the remote holds commit and tag. The
    # local record must stay, or the clone would disagree with origin.
    _stall_origin(repo, "post-receive", "0")
    env["TURBOSIGN_RELEASE_PUSH_TIMEOUT_S"] = "2"
    r = release(repo, env, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "released v1.3.0" in r.stdout
    assert "timed out" in r.stderr
    rel = git(repo["clone"], "rev-parse", "HEAD", env=env)
    assert origin_main(repo, env) == rel
    assert "v1.3.0" in origin_tags(repo, env).split()
    assert git(repo["clone"], "tag", "--list", "v1.3.0", env=env) == "v1.3.0"
# end def


def test_suite_that_moves_head_is_refused(repo, env):
    base = origin_main(repo, env)
    r = release(repo, env, "git commit -q --allow-empty -m sneaky; echo '1 passed'")
    assert r.returncode == 1
    assert "moved HEAD" in r.stderr
    assert_untouched(repo, env, base)
# end def


def test_a_version_whose_tag_already_exists_is_refused(repo, env, tmp_path):
    # v1.3.0 exists on a commit that never reached main.
    base = origin_main(repo, env)
    seed = repo["seed"]
    git(seed, "tag", "-a", "v1.3.0", "-m", "v1.3.0", "HEAD~1", env=env)
    git(seed, "push", "-q", "origin", "v1.3.0", env=env)
    fake = tmp_path / "relver"
    fake.write_text("#!/usr/bin/env bash\necho v1.3.0\n")
    fake.chmod(0o755)
    env["JJSTACK_RELEASE_VERSION"] = str(fake)
    marker = tmp_path / "ran"
    r = release(repo, env, f"touch {marker}")
    assert r.returncode == 1
    assert "tag v1.3.0 already exists" in r.stderr
    assert not marker.exists()
    assert git(repo["clone"], "rev-parse", "HEAD", env=env) == base
# end def


# --- the repo itself -------------------------------------------------------


def test_no_github_workflow_runs_ci():
    # Jesper, 2026-11-18: CI lives in the release script, never in Actions.
    workflows = ROOT / ".github" / "workflows"
    assert not workflows.exists() or not any(workflows.iterdir())
# end def


def test_the_default_suite_is_the_repo_suite_script():
    text = SCRIPT.read_text()
    assert 'suite="bash scripts/suite.sh"' in text
    assert SUITE_SCRIPT.is_file()
# end def
