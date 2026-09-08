"""Tests for delegation: eligibility, the task bank, and the work chain."""
from pathlib import Path

import pytest

from forge import delegation
from forge.delegation import Delegator, Pattern, State, Task, TaskBank
from forge.executor import Executor


@pytest.fixture
def bank(tmp_path):
    b = TaskBank(path=tmp_path / "d.db")
    yield b
    b.close()


def task(pattern="docstrings", file="mod.py", project="demo"):
    return Task(project=project, file=file, pattern=pattern)


class TestEligibility:
    @pytest.mark.parametrize("name", [
        "auth.py", "login.py", "crypto_utils.py", "payment_gateway.py",
        "session_store.py", "settings.py",
    ])
    def test_refuses_sensitive_files(self, tmp_path, name):
        f = tmp_path / name
        f.write_text("x = 1\n", encoding="utf-8")
        ok, reason = delegation.eligible(f)
        assert not ok
        assert "sensitive" in reason

    def test_refuses_frontend(self, tmp_path):
        f = tmp_path / "styles.css"
        f.write_text("a{}", encoding="utf-8")
        ok, reason = delegation.eligible(f)
        assert not ok
        assert "frontend" in reason

    def test_refuses_frozen_project(self, tmp_path):
        f = tmp_path / "util.py"
        f.write_text("x = 1\n", encoding="utf-8")
        ok, reason = delegation.eligible(f, project_name="ManosAbiertas")
        assert not ok
        assert "frozen" in reason

    def test_refuses_test_files(self, tmp_path):
        f = tmp_path / "test_thing.py"
        f.write_text("x = 1\n", encoding="utf-8")
        assert not delegation.eligible(f)[0]

    def test_refuses_migrations(self, tmp_path):
        d = tmp_path / "migrations"
        d.mkdir()
        f = d / "0001_initial.py"
        f.write_text("x = 1\n", encoding="utf-8")
        ok, reason = delegation.eligible(f)
        assert not ok
        assert "historical" in reason

    def test_refuses_empty_file(self, tmp_path):
        f = tmp_path / "empty.py"
        f.touch()
        assert not delegation.eligible(f)[0]

    def test_accepts_ordinary_module(self, tmp_path):
        f = tmp_path / "parser.py"
        f.write_text("def parse(x):\n    return x\n", encoding="utf-8")
        assert delegation.eligible(f)[0]


class TestCollect:
    def make_tree(self, root):
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        (root / "b.py").write_text("y = 2\n", encoding="utf-8")
        (root / "auth.py").write_text("z = 3\n", encoding="utf-8")
        vendor = root / "node_modules" / "pkg"
        vendor.mkdir(parents=True)
        (vendor / "c.py").write_text("w = 4\n", encoding="utf-8")

    def test_skips_vendor_and_sensitive(self, tmp_path):
        self.make_tree(tmp_path)
        found = {p.name for p in
                 delegation.collect(tmp_path, delegation.PATTERNS["docstrings"])}
        assert found == {"a.py", "b.py"}

    def test_is_deterministic(self, tmp_path):
        self.make_tree(tmp_path)
        pattern = delegation.PATTERNS["docstrings"]
        assert delegation.collect(tmp_path, pattern) == \
            delegation.collect(tmp_path, pattern)

    def test_respects_limit(self, tmp_path):
        self.make_tree(tmp_path)
        found = delegation.collect(tmp_path, delegation.PATTERNS["docstrings"],
                                   limit=1)
        assert len(found) == 1

    def test_skips_oversized_files(self, tmp_path):
        big = tmp_path / "big.py"
        big.write_text("# " + "x" * 50_000, encoding="utf-8")
        assert delegation.collect(tmp_path, delegation.PATTERNS["docstrings"]) == []


class TestTaskBank:
    def test_enqueue_returns_added_count(self, bank):
        assert bank.enqueue([task(), task(file="other.py")]) == 2

    def test_enqueue_is_idempotent(self, bank):
        bank.enqueue([task()])
        assert bank.enqueue([task()]) == 0

    def test_pending_returns_queued(self, bank):
        bank.enqueue([task()])
        assert len(bank.pending()) == 1

    def test_mark_done_removes_from_pending(self, bank):
        bank.enqueue([task()])
        bank.mark(task(), State.DONE, "ok")
        assert bank.pending() == []

    def test_counts_by_state(self, bank):
        bank.enqueue([task(), task(file="b.py")])
        bank.mark(task(), State.DONE)
        assert bank.counts() == {"done": 1, "pending": 1}

    def test_attempts_increment_on_running(self, bank):
        bank.enqueue([task()])
        bank.mark(task(), State.RUNNING)
        bank.mark(task(), State.PENDING)
        assert bank.pending()[0].attempts == 1

    def test_exhausted_tasks_drop_out(self, bank):
        bank.enqueue([task()])
        for _ in range(2):
            bank.mark(task(), State.RUNNING)
            bank.mark(task(), State.PENDING)
        assert bank.pending(max_attempts=2) == []

    def test_reset_running_recovers_crash(self, bank):
        bank.enqueue([task()])
        bank.mark(task(), State.RUNNING)
        assert bank.pending() == []
        assert bank.reset_running() == 1
        assert len(bank.pending()) == 1

    def test_survives_reopen(self, tmp_path):
        path = tmp_path / "d.db"
        first = TaskBank(path=path)
        first.enqueue([task()])
        first.close()

        second = TaskBank(path=path)
        assert len(second.pending()) == 1
        second.close()

    def test_detail_is_redacted(self, bank):
        bank.enqueue([task()])
        bank.mark(task(), State.FAILED, "key ghp_" + "a" * 36)
        assert "ghp_" not in bank.failures()[0].detail

    def test_failures_listed(self, bank):
        bank.enqueue([task()])
        bank.mark(task(), State.FAILED, "boom")
        assert bank.failures()[0].detail == "boom"


class TestPlanAndEstimate:
    def test_plan_covers_the_chain(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        tasks = delegation.plan("demo", tmp_path, chain="document")
        assert {t.pattern for t in tasks} == set(delegation.CHAINS["document"])

    def test_plan_uses_relative_posix_paths(self, tmp_path):
        sub = tmp_path / "pkg"
        sub.mkdir()
        (sub / "a.py").write_text("x = 1\n", encoding="utf-8")
        tasks = delegation.plan("demo", tmp_path, chain="scaffold")
        assert tasks[0].file == "pkg/a.py"

    def test_plan_skips_frozen_project(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        assert delegation.plan("linguaforge", tmp_path, chain="document") == []

    def test_estimate_counts_by_pattern(self, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        est = delegation.estimate(delegation.plan("demo", tmp_path, chain="document"))
        assert est["files"] == 1
        assert est["tasks"] == len(delegation.CHAINS["document"])


class TestDelegator:
    def test_command_targets_the_file(self):
        cmd = Delegator().command(task(), delegation.PATTERNS["docstrings"])
        assert cmd[0] == "forge-api"
        assert cmd[-1] == "mod.py"

    def test_command_does_not_invoke_aider(self):
        cmd = Delegator().command(task(), delegation.PATTERNS["docstrings"])
        assert "aider" not in cmd
        assert "--edit" in cmd

    def test_command_carries_the_model(self):
        cmd = Delegator(model="deepseek/deepseek-v4-pro").command(
            task(), delegation.PATTERNS["docstrings"])
        assert cmd[cmd.index("--model") + 1] == "deepseek/deepseek-v4-pro"

    def test_dry_run_executes_nothing(self, tmp_path):
        d = Delegator(executor=Executor(apply=False))
        state, detail = d.run_task(task(), tmp_path)
        assert state is State.PENDING
        assert "dry run" in detail

    def test_unknown_pattern_is_skipped(self, tmp_path):
        state, detail = Delegator().run_task(task(pattern="nope"), tmp_path)
        assert state is State.SKIPPED

    def test_verify_flags_broken_python(self, tmp_path):
        broken = tmp_path / "broken.py"
        broken.write_text("def f(:\n", encoding="utf-8")
        result = Delegator().verify(
            Task("demo", str(broken), "docstrings"),
            delegation.PATTERNS["docstrings"])
        assert not result.ok

    def test_verify_passes_valid_python(self, tmp_path):
        good = tmp_path / "good.py"
        good.write_text("def f():\n    return 1\n", encoding="utf-8")
        result = Delegator().verify(
            Task("demo", str(good), "docstrings"),
            delegation.PATTERNS["docstrings"])
        assert result.ok


class TestPatterns:
    def test_every_chain_references_real_patterns(self):
        for chain, names in delegation.CHAINS.items():
            for name in names:
                assert name in delegation.PATTERNS, "%s -> %s" % (chain, name)

    def test_every_pattern_has_a_rationale(self):
        assert all(p.rationale for p in delegation.PATTERNS.values())

    def test_every_pattern_verifies_the_file(self):
        for p in delegation.PATTERNS.values():
            assert any("{file}" in part for part in p.verify)


class TestDirectAPI:
    def test_extract_code_block_pulls_fence(self):
        text = "Sure, here:\n```python\nx = 1\n```\nDone."
        assert delegation._extract_code_block(text) == "x = 1\n"

    def test_extract_code_block_without_fence_returns_text(self):
        text = "no fence here"
        assert delegation._extract_code_block(text) == text

    def test_command_is_not_aider(self):
        cmd = Delegator().command(
            Task("demo", "mod.py", "docstrings"),
            delegation.PATTERNS["docstrings"])
        assert cmd[0] == "forge-api"
        assert "aider" not in cmd

    def test_edit_missing_key_returns_failure(self, tmp_path, monkeypatch):
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        f = tmp_path / "mod.py"
        f.write_text("x = 1\n", encoding="utf-8")
        d = Delegator(executor=Executor(apply=True))
        result = d.edit(Task("demo", "mod.py", "docstrings"),
                        delegation.PATTERNS["docstrings"], tmp_path)
        assert not result.ok
        assert "DEEPSEEK_API_KEY" in result.output
        assert f.read_text(encoding="utf-8") == "x = 1\n"

    def test_edit_dry_run_does_not_touch_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
        f = tmp_path / "mod.py"
        f.write_text("x = 1\n", encoding="utf-8")
        d = Delegator(executor=Executor(apply=False))
        result = d.edit(Task("demo", "mod.py", "docstrings"),
                        delegation.PATTERNS["docstrings"], tmp_path)
        assert result.dry_run
        assert f.read_text(encoding="utf-8") == "x = 1\n"
