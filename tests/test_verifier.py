"""Tests for the Definition of Done."""
from forge import verifier
from forge.executor import Executor
from forge.models import GitState, Project


def complete(tmp_path=None):
    return Project(
        name="complete", path=str(tmp_path) if tmp_path else "",
        has_readme=True, has_license=True, has_gitignore=True,
        has_tests=True, has_ci=True, file_count=42,
        git=GitState(repo=True, branch="main", dirty=0,
                     remote="https://github.com/u/complete"),
    )


def broken():
    return Project(name="broken", file_count=0, git=GitState(repo=False))


class TestChecks:
    def test_structure_flags_empty_project(self):
        checks = {c.name: c for c in verifier.check_structure(broken())}
        assert not checks["not_empty"].passed

    def test_structure_passes_for_complete(self):
        checks = {c.name: c for c in verifier.check_structure(complete())}
        assert all(c.passed for c in checks.values())

    def test_git_flags_missing_remote(self):
        checks = {c.name: c for c in verifier.check_git(broken())}
        assert not checks["has_remote"].passed
        assert not checks["git_repo"].passed

    def test_dirty_tree_is_non_blocking(self):
        p = complete()
        p.git.dirty = 12
        checks = {c.name: c for c in verifier.check_git(p)}
        assert not checks["clean_tree"].passed
        assert checks["clean_tree"].blocking is False


class TestSecretScan:
    def test_clean_directory_passes(self, tmp_path):
        (tmp_path / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
        assert verifier.check_secrets(tmp_path).passed

    def test_detects_planted_secret(self, tmp_path):
        (tmp_path / "conf.py").write_text(
            "TOKEN = 'ghp_" + "d" * 36 + "'", encoding="utf-8")
        assert not verifier.check_secrets(tmp_path).passed

    def test_ignores_node_modules(self, tmp_path):
        nested = tmp_path / "node_modules" / "pkg"
        nested.mkdir(parents=True)
        (nested / "i.js").write_text("k='ghp_" + "e" * 36 + "'", encoding="utf-8")
        assert verifier.check_secrets(tmp_path).passed


class TestDetectRunner:
    def test_python_via_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        assert verifier.detect_runner(tmp_path) == "python"

    def test_node_via_package_json(self, tmp_path):
        (tmp_path / "package.json").touch()
        assert verifier.detect_runner(tmp_path) == "node"

    def test_none_when_no_manifest(self, tmp_path):
        assert verifier.detect_runner(tmp_path) is None


class TestVerdict:
    def test_broken_project_not_done(self):
        assert not verifier.verify(broken()).done

    def test_blockers_listed(self):
        blockers = verifier.verify(broken()).blockers
        assert "not_empty" in {b.name for b in blockers}

    def test_score_between_zero_and_hundred(self):
        score = verifier.verify(complete()).score
        assert 0 <= score <= 100

    def test_complete_project_is_done(self, tmp_path):
        (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
        assert verifier.verify(complete(tmp_path)).done

    def test_to_dict_shape(self):
        payload = verifier.verify(broken()).to_dict()
        assert set(payload) == {"project", "done", "score", "checks", "blockers"}


class TestDeepMode:
    def test_dry_run_marks_tests_not_run(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        check = verifier.check_tests(tmp_path, Executor(apply=False))
        assert "dry run" in check.detail

    def test_build_skipped_for_python(self, tmp_path):
        (tmp_path / "pyproject.toml").touch()
        assert verifier.check_build(tmp_path, Executor(apply=False)).passed


class TestVerifyAll:
    def test_one_verdict_per_project(self):
        verdicts = verifier.verify_all([complete(), broken()])
        assert [v.project for v in verdicts] == ["complete", "broken"]
