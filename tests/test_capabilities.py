"""Tests for the capability audit.

The critical property under test: a credential value must never survive a
round-trip through this module.
"""
from forge import capabilities as caps


class TestMask:
    def test_never_returns_original(self):
        secret = "sk-abcdefghijklmnopqrstuvwxyz"  # gitleaks:allow
        assert caps.mask(secret) != secret

    def test_keeps_only_edges(self):
        assert caps.mask("sk-abcdefghijklmnop") == "sk-a…op"  # gitleaks:allow

    def test_short_value_fully_starred(self):
        assert caps.mask("abc123") == "******"

    def test_empty_stays_empty(self):
        assert caps.mask("") == ""

    def test_middle_is_never_leaked(self):
        secret = "sk-SENSITIVEMIDDLEPART99"  # gitleaks:allow
        assert "SENSITIVEMIDDLE" not in caps.mask(secret)


class TestDetectProviders:
    def test_reports_only_masked_values(self):
        env = {"OPENAI_API_KEY": "sk-realsecretvalue1234"}  # gitleaks:allow
        found = caps.detect_providers(env)
        assert found["OPENAI_API_KEY"] != env["OPENAI_API_KEY"]
        assert "realsecret" not in found["OPENAI_API_KEY"]

    def test_unset_vars_absent(self):
        assert caps.detect_providers({}) == {}

    def test_empty_value_treated_as_unset(self):
        assert caps.detect_providers({"OPENAI_API_KEY": ""}) == {}

    def test_ignores_unknown_variables(self):
        assert caps.detect_providers({"NOT_A_PROVIDER": "x" * 20}) == {}


class TestTools:
    def test_python_is_detected(self):
        tools = {t.name: t for t in caps.detect_tools(["python"])}
        assert tools["python"].installed

    def test_missing_tool_reported(self):
        tools = {t.name: t for t in caps.detect_tools(["not-a-real-binary-xyz"])}
        assert not tools["not-a-real-binary-xyz"].installed

    def test_purpose_populated_for_known(self):
        assert caps.detect_tools(["git"])[0].purpose


class TestCapabilities:
    def test_delegation_prefers_local_model(self):
        c = caps.Capabilities(local_models=["llama3.2"])
        assert c.delegation_target() == "ollama:llama3.2"

    def test_delegation_falls_back_to_aider(self):
        c = caps.Capabilities(
            tools=[caps.Tool(name="aider", installed=True)],
            providers={"DEEPSEEK_API_KEY": "sk-a…9f"})
        assert c.delegation_target() == "aider"

    def test_no_delegation_target_when_bare(self):
        assert caps.Capabilities().delegation_target() is None

    def test_installed_and_missing_partition(self):
        c = caps.Capabilities(tools=[
            caps.Tool(name="git", installed=True),
            caps.Tool(name="nope", installed=False),
        ])
        assert c.installed() == ["git"]
        assert c.missing() == ["nope"]

    def test_to_dict_never_carries_raw_secret(self):
        c = caps.Capabilities(providers=caps.detect_providers(
            {"OPENAI_API_KEY": "sk-donotleakthisvalue99"}))  # gitleaks:allow
        assert "donotleakthis" not in str(c.to_dict())


class TestAudit:
    def test_returns_populated_report(self):
        report = caps.audit()
        assert report.generated
        assert report.tools
