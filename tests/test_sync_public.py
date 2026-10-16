"""devtools/Sync-PublicRepo.ps1 against throw-away repositories (a private one, a bare 'GitHub', a public clone)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "devtools" / "Sync-PublicRepo.ps1"
PWSH = shutil.which("pwsh")
NOREPLY = "1+someone@users.noreply.github.com"
pytestmark = pytest.mark.skipif(sys.platform != "win32" or PWSH is None or shutil.which("git") is None,
                                reason="needs Windows, pwsh 7 and git")


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          encoding="utf-8", env=env).stdout.strip()


def commit_all(repo, message="change"):
    git(repo, "add", "--all")
    git(repo, "commit", "-q", "-m", message)


def identity(repo, email):
    git(repo, "config", "user.email", email)
    git(repo, "config", "user.name", "Someone")


@pytest.fixture
def repos(tmp_path):
    private, origin, public = tmp_path / "private repo", tmp_path / "origin.git", tmp_path / "public repo"
    private.mkdir()
    git(private, "init", "-q", "-b", "main")
    identity(private, "secret@example.com")
    (private / "README.md").write_text("new readme\n", encoding="utf-8")
    (private / "src").mkdir()
    (private / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (private / "assets").mkdir()
    (private / "assets" / "icon.ico").write_bytes(bytes(range(256)) * 4 + b"\r\n\x00\x1a")
    (private / "docs").mkdir()
    (private / "docs" / "中文 说明.md").write_text("你好\n", encoding="utf-8")
    (private / "run.sh").write_text("echo hi\n", encoding="utf-8")
    git(private, "add", "--all")
    git(private, "update-index", "--chmod=+x", "run.sh")
    git(private, "commit", "-q", "-m", "private work")

    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    public.mkdir()
    git(public, "init", "-q", "-b", "main")
    identity(public, NOREPLY)
    (public / "README.md").write_text("old readme\n", encoding="utf-8")
    (public / "stale.txt").write_text("gone soon\n", encoding="utf-8")
    commit_all(public, "initial")
    git(public, "remote", "add", "origin", str(origin))
    git(public, "push", "-q", "-u", "origin", "main")
    return private, origin, public


def scanner(tmp_path, exit_code=0, **extra_env):
    """A stand-in gitleaks first on PATH (the real one is not needed to test the script's own logic)."""
    folder = tmp_path / "bin"
    folder.mkdir(exist_ok=True)
    (folder / "gitleaks.cmd").write_text(f"@exit /b {exit_code}\n", encoding="ascii")
    return {**os.environ, "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}", **extra_env}


def sync(private, public, *extra, env=None):
    run = subprocess.run([PWSH, "-NoProfile", "-File", str(SCRIPT), "-PrivateRepo", str(private),
                          "-PublicRepo", str(public), *extra],
                         capture_output=True, text=True, encoding="utf-8", env=env or os.environ)
    run.output = run.stdout + run.stderr
    return run


def snapshot(repo):
    """Everything a refused sync must leave alone."""
    return (git(repo, "rev-parse", "HEAD"), git(repo, "ls-files", "--stage"),
            git(repo, "status", "--porcelain", "--untracked-files=all", "--ignored"))


def published(origin, private):
    return git(origin, "rev-parse", "main^{tree}") == git(private, "rev-parse", "main^{tree}")


def test_a_dry_run_lists_the_changes_and_touches_nothing(repos):
    private, origin, public = repos
    before = snapshot(public)
    run = sync(private, public)
    assert run.returncode == 0, run.output
    assert "A\tsrc/app.py" in run.stdout and "A\tdocs/中文 说明.md" in run.stdout
    assert "M\tREADME.md" in run.stdout and "D\tstale.txt" in run.stdout and "Dry run" in run.stdout
    assert snapshot(public) == before and not published(origin, private)


def test_push_publishes_exactly_the_private_tree_without_its_history(repos, tmp_path):
    private, origin, public = repos
    run = sync(private, public, "-Push", "-Message", "Sync test", env=scanner(tmp_path))
    assert run.returncode == 0, run.output
    assert published(origin, private)  # same tree id: paths, bytes and modes (run.sh stays executable)
    assert git(public, "rev-parse", "HEAD") == git(origin, "rev-parse", "main")
    assert git(public, "status", "--porcelain", "--untracked-files=all") == ""
    assert "100755" in git(origin, "ls-tree", "main", "run.sh")
    assert set(git(origin, "log", "--format=%ae%n%ce", "main").split()) == {NOREPLY}  # no private author
    assert git(origin, "log", "-1", "--format=%s", "main") == "Sync test"
    private_commit = git(private, "rev-parse", "main")
    probe = subprocess.run(["git", "-C", str(origin), "cat-file", "-e", private_commit], capture_output=True)
    assert probe.returncode != 0  # the private commit object never reached the public remote
    again = sync(private, public)
    assert again.returncode == 0 and "Already in sync" in again.stdout


def test_case_renames_and_file_folder_swaps_are_published(repos, tmp_path):
    private, origin, public = repos
    env = scanner(tmp_path)
    (public / "data").write_text("a file\n", encoding="utf-8")  # public: data is a file
    commit_all(public, "data file")
    git(public, "push", "-q", "origin", "main")
    (private / "data").mkdir()  # private: data is a folder
    (private / "data" / "item.txt").write_text("inside\n", encoding="utf-8")
    git(private, "mv", "README.md", "Readme.md")  # case-only rename
    commit_all(private, "rename and folder")
    run = sync(private, public, "-Push", env=env)
    assert run.returncode == 0, run.output
    assert published(origin, private) and "Readme.md" in git(origin, "ls-tree", "--name-only", "main")
    shutil.rmtree(private / "data")  # and back: folder -> file
    (private / "data").write_text("a file again\n", encoding="utf-8")
    commit_all(private, "folder to file")
    run = sync(private, public, "-Push", env=env)
    assert run.returncode == 0, run.output
    assert published(origin, private)


def test_identity_variables_cannot_put_a_real_email_into_the_public_history(repos, tmp_path):
    private, origin, public = repos
    env = scanner(tmp_path, GIT_AUTHOR_EMAIL="real@example.com", GIT_COMMITTER_EMAIL="real@example.com",
                  GIT_AUTHOR_NAME="Real Name")
    run = sync(private, public, "-Push", env=env)
    assert run.returncode == 0, run.output
    assert set(git(origin, "log", "--format=%ae%n%ce%n%an", "main").split("\n")) == {NOREPLY, "Someone"}


@pytest.mark.parametrize("problem, reason", [
    ("dirty", "uncommitted or untracked"),
    ("untracked", "uncommitted or untracked"),
    ("email", "noreply"),
    ("behind", "not in step"),
])
def test_an_unsafe_public_repo_is_refused_before_anything_changes(repos, tmp_path, problem, reason):
    private, origin, public = repos
    if problem == "dirty":
        (public / "README.md").write_text("edited\n", encoding="utf-8")
    elif problem == "untracked":
        git(public, "config", "status.showUntrackedFiles", "no")  # must not hide a file the sync would overwrite
        (public / "src").mkdir()
        (public / "src" / "app.py").write_text("my local work\n", encoding="utf-8")
    elif problem == "email":
        git(public, "config", "user.email", "real.person@example.com")
    else:  # someone pushed to GitHub meanwhile
        other = tmp_path / "other clone"
        subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
        identity(other, NOREPLY)
        (other / "extra.txt").write_text("x\n", encoding="utf-8")
        commit_all(other)
        git(other, "push", "-q", "origin", "main")
    before, remote = snapshot(public), git(origin, "rev-parse", "main")
    run = sync(private, public, "-Push", env=scanner(tmp_path))
    assert run.returncode != 0 and reason in run.output
    assert git(origin, "rev-parse", "main") == remote
    if problem != "behind":  # (the check itself fetches origin, which only moves origin/main)
        assert snapshot(public) == before
    if problem == "untracked":
        assert (public / "src" / "app.py").read_text(encoding="utf-8") == "my local work\n"


def test_nothing_is_pushed_or_changed_when_gitleaks_objects(repos, tmp_path):
    private, origin, public = repos
    before, remote = snapshot(public), git(origin, "rev-parse", "main")
    run = sync(private, public, "-Push", env=scanner(tmp_path, exit_code=1))
    assert run.returncode != 0 and "Not pushed" in run.output
    assert git(origin, "rev-parse", "main") == remote and snapshot(public) == before


def test_an_ignored_local_file_in_the_way_is_refused(repos, tmp_path):
    private, origin, public = repos
    exclude = public / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("src/app.py\n", encoding="utf-8")
    (public / "src").mkdir()
    (public / "src" / "app.py").write_text("my ignored local work\n", encoding="utf-8")
    remote = git(origin, "rev-parse", "main")
    run = sync(private, public, "-Push", env=scanner(tmp_path))
    assert run.returncode != 0 and "ignored local files" in run.output
    assert git(origin, "rev-parse", "main") == remote
    assert (public / "src" / "app.py").read_text(encoding="utf-8") == "my ignored local work\n"


def test_the_public_object_store_never_holds_private_commits(repos, tmp_path):
    private, _origin, public = repos
    private_commit = git(private, "rev-parse", "main")

    def present():
        return subprocess.run(["git", "-C", str(public), "cat-file", "-e", private_commit],
                              capture_output=True).returncode == 0

    assert sync(private, public).returncode == 0 and not present()  # dry run
    run = sync(private, public, "-Push", env=scanner(tmp_path))
    assert run.returncode == 0, run.output
    assert not present()
    leftovers = [d for d in Path(os.environ.get("TEMP", tmp_path)).glob("desk-sister-sync-*")]
    assert leftovers == []  # the temporary repository is gone


def test_defaults_work_from_the_private_root(repos):
    private, _origin, public = repos
    sibling = public.with_name("desk-sister")
    public.rename(sibling)
    run = subprocess.run([PWSH, "-NoProfile", "-File", str(SCRIPT), "-PrivateRepo", "."], cwd=private,
                         capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stdout + run.stderr
    assert f"Target: {sibling}" in run.stdout and "Dry run" in run.stdout


def test_only_main_is_pushed_even_with_follow_tags(repos, tmp_path):
    private, origin, public = repos
    git(public, "config", "push.followTags", "true")
    git(public, "tag", "-a", "local-note", "-m", "private note, never checked")
    run = sync(private, public, "-Push", env=scanner(tmp_path))
    assert run.returncode == 0, run.output
    assert published(origin, private) and git(origin, "tag", "--list") == ""



def test_a_relative_origin_is_resolved_from_the_public_checkout(repos, tmp_path):
    private, origin, public = repos
    git(public, "remote", "set-url", "origin", "../origin.git")  # relative to the public checkout
    run = sync(private, public, "-Push", env=scanner(tmp_path))
    assert run.returncode == 0, run.output
    assert published(origin, private) and git(public, "rev-parse", "HEAD") == git(origin, "rev-parse", "main")


def test_the_push_goes_where_git_push_would_go(repos, tmp_path):
    private, origin, public = repos
    writable = tmp_path / "write.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(origin), str(writable)], check=True)
    git(public, "remote", "set-url", "--push", "origin", str(writable))  # read here, write there
    read_side = git(origin, "rev-parse", "main")
    run = sync(private, public, "-Push", env=scanner(tmp_path))
    assert run.returncode == 0, run.output
    assert git(writable, "rev-parse", "main^{tree}") == git(private, "rev-parse", "main^{tree}")
    assert git(origin, "rev-parse", "main") == read_side  # the fetch URL is not written to

