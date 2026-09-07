"""Tests for safe git operations."""
import subprocess

import pytest

from forge.executor import Executor
from forge.git_manager import GitManager


@pytest.fixture
def repo(tmp_path):
    """A real git repository with one commit."""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init", "--no-verify"],
                   cwd=tmp_path, check=True)
    return tmp_path


class TestInspection:
    def test_detects_repository(self, repo):
        assert GitManager(repo, Executor(apply=True)).is_repo()

    def test_non_repo_detected(self, tmp_path):
        assert not GitManager(tmp_path, Executor(apply=True)).is_repo()

    def test_state_of_clean_repo(self, repo):
        state = GitManager(repo, Executor(apply=True)).state()
        assert state.repo
        assert state.branch == "main"
        assert state.dirty == 0
        assert state.remote == "none"

    def test_state_of_non_repo_is_empty(self, tmp_path):
        assert not GitManager(tmp_path, Executor(apply=True)).state().repo

    def test_dirty_count_tracks_changes(self, repo):
        (repo / "new.py").write_text("x = 1\n", encoding="utf-8")
        assert GitManager(repo, Executor(apply=True)).state().dirty == 1

    def test_dirty_files_listed(self, repo):
        (repo / "new.py").write_text("x = 1\n", encoding="utf-8")
        files = GitManager(repo, Executor(apply=True)).dirty_files()
        assert any(f.name == "new.py" for f in files)

    def test_last_commit_recorded(self, repo):
        assert "init" in GitManager(repo, Executor(apply=True)).state().last_commit


class TestSafeCommit:
    def test_refuses_when_secret_present(self, repo):
        (repo / "conf.py").write_text(
            "TOKEN = 'ghp_" + "f" * 36 + "'", encoding="utf-8")
        res = GitManager(repo, Executor(apply=True)).safe_commit("add config")
        assert res.code == 126
        assert "refused" in res.output

    def test_refuses_env_file(self, repo):
        """A force-added .env is the realistic accident this must catch."""
        (repo / ".env").write_text("SECRET=1\n", encoding="utf-8")
        subprocess.run(["git", "add", "-f", ".env"], cwd=repo, check=True)
        res = GitManager(repo, Executor(apply=True)).safe_commit("add env")
        assert res.code == 126
        assert "environment file" in res.output

    def test_commits_clean_change(self, repo):
        (repo / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        res = GitManager(repo, Executor(apply=True)).safe_commit("add module")
        assert res.ok
        assert GitManager(repo, Executor(apply=True)).state().dirty == 0


class TestSafePush:
    def test_refuses_dirty_tree(self, repo):
        (repo / "x.py").write_text("x = 1\n", encoding="utf-8")
        res = GitManager(repo, Executor(apply=True)).safe_push()
        assert res.code == 126
        assert "uncommitted" in res.output

    def test_refuses_without_remote(self, repo):
        res = GitManager(repo, Executor(apply=True)).safe_push()
        assert res.code == 126
        assert "no remote" in res.output


class TestSync:
    def test_refuses_dirty_tree(self, repo):
        (repo / "x.py").write_text("x = 1\n", encoding="utf-8")
        res = GitManager(repo, Executor(apply=True)).sync()
        assert res.code == 126
        assert "at risk" in res.output


class TestDryRun:
    def test_commit_not_executed(self, repo):
        (repo / "mod.py").write_text("y = 2\n", encoding="utf-8")
        gm = GitManager(repo, Executor(apply=False))
        gm.safe_commit("should not land")
        assert gm.state().dirty == 1

    def test_snapshot_branch_is_dry(self, repo):
        gm = GitManager(repo, Executor(apply=False))
        assert gm.snapshot_branch("before-change").dry_run
