"""Tests for the safety layer."""
import pytest

from forge import safety
from forge.safety import SafetyViolation


class TestRedact:
    def test_masks_aws_key(self):
        out = safety.redact("key = AKIAQYLPMN5HXH7ZWDR3")  # gitleaks:allow
        assert "AKIAQYLPMN5HXH7ZWDR3" not in out  # gitleaks:allow

    def test_aws_documentation_example_is_not_flagged(self):
        """AWS's published EXAMPLE key is a placeholder, not a leak."""
        text = "key = AKIAIOSFODNN7EXAMPLE"  # gitleaks:allow
        assert safety.redact(text) == text

    def test_masks_github_token(self):
        out = safety.redact("ghp_" + "a" * 36)
        assert out == safety.REDACTED

    def test_masks_private_key_header(self):
        assert safety.REDACTED in safety.redact("-----BEGIN RSA PRIVATE KEY-----")  # gitleaks:allow

    def test_keeps_placeholders(self):
        text = 'API_KEY="your_key_here"'
        assert safety.redact(text) == text

    def test_keeps_env_lookups(self):
        text = 'token = os.environ["TOKEN"]'
        assert safety.redact(text) == text

    def test_masks_gmail(self):
        assert "gmail.com" not in safety.redact("contact: someone@gmail.com")

    def test_masks_beep_account(self):
        assert "user-beep" not in safety.redact("account user-beep is private")

    def test_empty_input(self):
        assert safety.redact("") == ""

    def test_redact_all(self):
        out = safety.redact_all(["clean text", "ghp_" + "b" * 36])
        assert out[0] == "clean text"
        assert out[1] == safety.REDACTED


class TestFindSecrets:
    def test_reports_line_number(self):
        text = "line one\nsecret = AKIAQYLPMN5HXH7ZWDR3\nline three"  # gitleaks:allow
        hits = safety.find_secrets(text)
        assert hits and hits[0][1] == 2

    def test_ignores_placeholder_lines(self):
        assert safety.find_secrets('key = "changeme_placeholder_value"') == []

    def test_clean_text_has_no_hits(self):
        assert safety.find_secrets("def main():\n    return 0") == []


class TestFrontendGuard:
    @pytest.mark.parametrize("name", ["a.css", "b.html", "c.tsx", "d.glsl", "e.png"])
    def test_detects_frontend_files(self, name):
        assert safety.is_frontend_path(name)

    @pytest.mark.parametrize("name", ["a.py", "b.json", "c.toml", "d.md"])
    def test_allows_engineering_files(self, name):
        assert not safety.is_frontend_path(name)

    def test_guard_write_blocks_css(self):
        with pytest.raises(SafetyViolation, match="frontend frozen"):
            safety.guard_write("styles.css")

    def test_guard_write_allows_python(self):
        safety.guard_write("module.py")

    def test_guard_write_blocks_frozen_project(self):
        with pytest.raises(SafetyViolation, match="frozen"):
            safety.guard_write("notes.md", project_name="ManosAbiertas")

    def test_frozen_project_lookup(self):
        assert safety.is_frozen_project("linguaforge")
        assert not safety.is_frozen_project("belentani-forge")


class TestCommandGuard:
    @pytest.mark.parametrize("cmd", [
        ["git", "reset", "--hard"],
        ["git", "clean", "-fd"],
        ["git", "push", "--force"],
        ["git", "push", "-f"],
    ])
    def test_blocks_destructive_git(self, cmd):
        with pytest.raises(SafetyViolation):
            safety.guard_command(cmd)

    @pytest.mark.parametrize("cmd", [
        ["git", "status"], ["git", "log"], ["git", "commit", "-m", "x"],
        ["git", "push", "origin", "main"],
    ])
    def test_allows_safe_git(self, cmd):
        safety.guard_command(cmd)

    def test_blocks_rm(self):
        with pytest.raises(SafetyViolation):
            safety.guard_command(["rm", "-rf", "/"])

    def test_authorized_override_works(self):
        safety.guard_command(["git", "reset", "--hard"], authorized=True)

    def test_empty_command_rejected(self):
        with pytest.raises(SafetyViolation, match="empty"):
            safety.guard_command([])


class TestSafeToCommit:
    def test_flags_env_file(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("X=1", encoding="utf-8")
        problems = safety.safe_to_commit([env])
        assert any("environment file" in p for p in problems)

    def test_flags_private_key(self, tmp_path):
        key = tmp_path / "id.pem"
        key.write_text("data", encoding="utf-8")
        assert any("private key" in p for p in safety.safe_to_commit([key]))

    def test_flags_secret_in_source(self, tmp_path):
        src = tmp_path / "conf.py"
        src.write_text("TOKEN = 'ghp_" + "c" * 36 + "'", encoding="utf-8")
        assert safety.safe_to_commit([src])

    def test_clean_file_passes(self, tmp_path):
        src = tmp_path / "ok.py"
        src.write_text("def main():\n    return 0\n", encoding="utf-8")
        assert safety.safe_to_commit([src]) == []
