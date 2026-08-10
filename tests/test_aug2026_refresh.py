"""Tests for the August 2026 refresh: non-retryable error fast-fail,
Codex ChatGPT-account preflight, and the Antigravity CLI provider."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "gtm-forge" / "scripts"))

import models
import providers
from models import (
    CODEX_CHATGPT_HINT,
    _call_with_retry,
    is_non_retryable_error,
    resolve_antigravity_model,
)
from providers import (
    CODEX_CHATGPT_MODELS,
    codex_auth_mode,
    warn_codex_chatgpt_model_support,
    warn_openai_base_url_override,
)


class TestNonRetryableErrors:
    def test_chatgpt_account_model_rejection(self):
        msg = (
            '{"type":"error","status":400,"error":{"type":"invalid_request_error",'
            '"message":"The \'gpt-5.3-codex\' model is not supported when using '
            'Codex with a ChatGPT account."}}'
        )
        assert is_non_retryable_error(msg)

    def test_invalid_request_error(self):
        assert is_non_retryable_error("litellm.BadRequestError: invalid_request_error")

    def test_model_not_found(self):
        assert is_non_retryable_error("model_not_found: no such model")
        assert is_non_retryable_error(
            "The model `gpt-9` does not exist or you do not have access to it"
        )

    def test_auth_errors(self):
        assert is_non_retryable_error("litellm.AuthenticationError: bad key")
        assert is_non_retryable_error("Incorrect API key provided")

    def test_antigravity_deterministic_errors(self):
        assert is_non_retryable_error(
            "Antigravity CLI is not authenticated. Run `agy` interactively once"
        )
        assert is_non_retryable_error(
            "Antigravity CLI returned status ERROR: invalid model selection"
        )

    def test_bedrock_deterministic_errors(self):
        assert is_non_retryable_error(
            "Model not enabled in your Bedrock account: claude-opus-5"
        )
        assert is_non_retryable_error("Invalid Bedrock model ID: bogus.model")

    def test_transient_errors_still_retry(self):
        assert not is_non_retryable_error("rate limit exceeded")
        assert not is_non_retryable_error("connection reset by peer")
        assert not is_non_retryable_error("timed out after 600s")
        assert not is_non_retryable_error("500 Internal Server Error")

    def test_retry_loop_fails_fast_on_non_retryable(self):
        calls = []

        def failing_call(*args, **kwargs):
            calls.append(1)
            raise RuntimeError(
                "The 'gpt-5.3-codex' model is not supported when using Codex "
                "with a ChatGPT account."
            )

        with (
            patch("models._call_model_raw", side_effect=failing_call),
            patch("models.time.sleep") as mock_sleep,
        ):
            with pytest.raises(RuntimeError) as excinfo:
                _call_with_retry("codex/gpt-5.3-codex", "sys", "user")

        assert len(calls) == 1  # single attempt, no retries
        mock_sleep.assert_not_called()
        assert CODEX_CHATGPT_HINT in str(excinfo.value)

    def test_retry_loop_retries_transient_errors(self):
        calls = []

        def failing_call(*args, **kwargs):
            calls.append(1)
            raise RuntimeError("rate limit exceeded")

        with (
            patch("models._call_model_raw", side_effect=failing_call),
            patch("models.time.sleep"),
        ):
            with pytest.raises(RuntimeError, match="rate limit"):
                _call_with_retry("codex/gpt-5.5", "sys", "user")

        assert len(calls) == models.MAX_RETRIES

    def test_retry_loop_success_passthrough(self):
        with patch("models._call_model_raw", return_value=("hello", 10, 5)):
            content, inp, out = _call_with_retry("gpt-5.5", "sys", "user")
        assert content == "hello"
        assert (inp, out) == (10, 5)


class TestCodexChatGPTPreflight:
    def test_chatgpt_lineup_membership(self):
        assert "gpt-5.6-sol" in CODEX_CHATGPT_MODELS
        assert "gpt-5.5" in CODEX_CHATGPT_MODELS
        assert "gpt-5.3-codex" not in CODEX_CHATGPT_MODELS
        assert "gpt-5.5-pro" not in CODEX_CHATGPT_MODELS

    def test_auth_mode_chatgpt(self, tmp_path, monkeypatch):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        (codex_dir / "auth.json").write_text(
            json.dumps({"auth_mode": "chatgpt", "tokens": {"x": 1}})
        )
        monkeypatch.setattr(providers.Path, "home", staticmethod(lambda: tmp_path))
        assert codex_auth_mode() == "chatgpt"

    def test_auth_mode_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(providers.Path, "home", staticmethod(lambda: tmp_path))
        assert codex_auth_mode() is None

    def test_auth_mode_non_dict_json(self, tmp_path, monkeypatch):
        codex_dir = tmp_path / ".codex"
        codex_dir.mkdir()
        for content in ("null", "[]", '"chatgpt"'):
            (codex_dir / "auth.json").write_text(content)
            monkeypatch.setattr(
                providers.Path, "home", staticmethod(lambda: tmp_path)
            )
            assert codex_auth_mode() is None

    def test_warns_on_unsupported_model(self, capsys):
        with patch("providers.codex_auth_mode", return_value="chatgpt"):
            warn_codex_chatgpt_model_support(["codex/gpt-5.3-codex", "gpt-5.5"])
        err = capsys.readouterr().err
        assert "gpt-5.3-codex" in err
        assert "ChatGPT account" in err

    def test_silent_on_supported_models(self, capsys):
        with patch("providers.codex_auth_mode", return_value="chatgpt"):
            warn_codex_chatgpt_model_support(["codex/gpt-5.6-sol", "codex/gpt-5.5"])
        assert capsys.readouterr().err == ""

    def test_silent_on_apikey_auth(self, capsys):
        with patch("providers.codex_auth_mode", return_value="apikey"):
            warn_codex_chatgpt_model_support(["codex/gpt-5.3-codex"])
        assert capsys.readouterr().err == ""

    def test_silent_without_codex_models(self, capsys):
        with patch("providers.codex_auth_mode", return_value="chatgpt"):
            warn_codex_chatgpt_model_support(["gpt-5.5", "claude-opus-5"])
        assert capsys.readouterr().err == ""


class TestCodexErrorParsing:
    def _run_codex(self, stdout, returncode=0):
        fake = type(
            "P", (), {"returncode": returncode, "stdout": stdout, "stderr": ""}
        )()
        with (
            patch("models.CODEX_AVAILABLE", True),
            patch("models.CODEX_PATH", "/usr/bin/codex"),
            patch("models.subprocess.run", return_value=fake),
        ):
            return models.call_codex_model("sys", "user", "codex/gpt-5.5")

    def test_string_error_field_parsed(self):
        stdout = json.dumps({"type": "turn.failed", "error": "usage limit reached"})
        with pytest.raises(RuntimeError, match="usage limit reached"):
            self._run_codex(stdout)

    def test_null_error_field_does_not_crash(self):
        lines = [
            json.dumps({"type": "error", "error": None}),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": "hi"},
                }
            ),
        ]
        text, _, _ = self._run_codex("\n".join(lines))
        assert text == "hi"

    def test_non_dict_jsonl_line_skipped(self):
        lines = [
            json.dumps(["not", "a", "dict"]),
            json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "ok"}}),
        ]
        text, _, _ = self._run_codex("\n".join(lines))
        assert text == "ok"

    def test_timeout_raises_clean_message(self):
        import subprocess as sp

        with (
            patch("models.CODEX_AVAILABLE", True),
            patch("models.CODEX_PATH", "/usr/bin/codex"),
            patch(
                "models.subprocess.run",
                side_effect=sp.TimeoutExpired(
                    cmd=["codex", "exec", "secret doc with invalid API key text"],
                    timeout=600,
                ),
            ),
        ):
            with pytest.raises(RuntimeError) as excinfo:
                models.call_codex_model("sys", "user", "codex/gpt-5.5")
        # Clean message: no argv/document leakage, stays retryable
        assert str(excinfo.value) == "Codex CLI timed out after 600s"
        assert not is_non_retryable_error(str(excinfo.value))


class TestAntigravityProvider:
    def test_resolve_slug_passthrough(self):
        assert (
            resolve_antigravity_model("antigravity/gemini-3.1-pro-high")
            == "gemini-3.1-pro-high"
        )
        assert (
            resolve_antigravity_model("antigravity/claude-sonnet-4-6")
            == "claude-sonnet-4-6"
        )

    def test_resolve_bare_antigravity_uses_default(self):
        assert resolve_antigravity_model("antigravity") is None

    def test_call_parses_agy_json(self):
        payload = {
            "conversation_id": "abc",
            "status": "SUCCESS",
            "response": "OK\n",
            "usage": {"input_tokens": 17579, "output_tokens": 26},
        }
        fake = type(
            "P", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}
        )()
        with (
            patch("models.ANTIGRAVITY_AVAILABLE", True),
            patch("models.ANTIGRAVITY_PATH", "/usr/bin/agy"),
            patch("models.subprocess.run", return_value=fake) as mock_run,
        ):
            text, inp, out = models.call_antigravity_model(
                "sys", "user", "antigravity/gemini-3.1-pro-high"
            )
        assert text == "OK"
        assert (inp, out) == (17579, 26)
        cmd = mock_run.call_args[0][0]
        assert "--model" in cmd and "gemini-3.1-pro-high" in cmd
        assert "--output-format" in cmd and "json" in cmd

    def test_call_raises_on_error_status(self):
        payload = {
            "status": "ERROR",
            "response": "",
            "error": "invalid model selection",
        }
        fake = type(
            "P", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}
        )()
        with (
            patch("models.ANTIGRAVITY_AVAILABLE", True),
            patch("models.ANTIGRAVITY_PATH", "/usr/bin/agy"),
            patch("models.subprocess.run", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="invalid model selection"):
                models.call_antigravity_model("sys", "user", "antigravity/bogus")

    def test_call_detects_unauthenticated(self):
        fake = type(
            "P",
            (),
            {
                "returncode": 1,
                "stdout": "Waiting for authentication (timeout 30s)...",
                "stderr": "",
            },
        )()
        with (
            patch("models.ANTIGRAVITY_AVAILABLE", True),
            patch("models.ANTIGRAVITY_PATH", "/usr/bin/agy"),
            patch("models.subprocess.run", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="not authenticated"):
                models.call_antigravity_model("sys", "user", "antigravity")

    def test_call_rejects_json_without_response_field(self):
        payload = {"conversation_id": "abc", "status": "SUCCESS"}
        fake = type(
            "P", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""}
        )()
        with (
            patch("models.ANTIGRAVITY_AVAILABLE", True),
            patch("models.ANTIGRAVITY_PATH", "/usr/bin/agy"),
            patch("models.subprocess.run", return_value=fake),
        ):
            with pytest.raises(RuntimeError, match="No response text"):
                models.call_antigravity_model("sys", "user", "antigravity")

    def test_call_falls_back_to_raw_text_output(self):
        fake = type(
            "P", (), {"returncode": 0, "stdout": "plain text answer", "stderr": ""}
        )()
        with (
            patch("models.ANTIGRAVITY_AVAILABLE", True),
            patch("models.ANTIGRAVITY_PATH", "/usr/bin/agy"),
            patch("models.subprocess.run", return_value=fake),
        ):
            text, _, _ = models.call_antigravity_model("sys", "user", "antigravity")
        assert text == "plain text answer"

    def test_validate_credentials_antigravity(self):
        with patch("providers.ANTIGRAVITY_AVAILABLE", True):
            valid, invalid = providers.validate_model_credentials(
                ["antigravity/gemini-3.1-pro-high"]
            )
        assert valid == ["antigravity/gemini-3.1-pro-high"]
        with patch("providers.ANTIGRAVITY_AVAILABLE", False):
            valid, invalid = providers.validate_model_credentials(
                ["antigravity/gemini-3.1-pro-high"]
            )
        assert invalid == ["antigravity/gemini-3.1-pro-high"]

    def test_antigravity_cost_is_free(self):
        assert providers.get_model_cost("antigravity/gemini-3.1-pro-high") == {
            "input": 0.0,
            "output": 0.0,
        }
        assert providers.get_model_cost("antigravity") == {
            "input": 0.0,
            "output": 0.0,
        }

    def test_antigravity_prefix_does_not_swallow_similar_ids(self):
        # "antigravity-pro" is not the agy CLI; it must not report zero cost
        assert providers.get_model_cost("antigravity-pro") == providers.DEFAULT_COST


class TestOpenAIBaseUrlWarning:
    def _clean_env(self):
        return patch.dict(
            "os.environ",
            {"OPENAI_BASE_URL": "", "OPENAI_API_BASE": ""},
            clear=False,
        )

    def test_warns_on_overridden_url_with_openai_model(self, capsys):
        with self._clean_env(), patch.dict(
            "os.environ", {"OPENAI_BASE_URL": "https://proxy.azure.example/v1"}
        ):
            warn_openai_base_url_override(["gpt-5.6-sol"])
        err = capsys.readouterr().err
        assert "OPENAI_BASE_URL" in err
        assert "proxy.azure.example" in err

    def test_warns_via_openai_api_base_alias(self, capsys):
        with self._clean_env(), patch.dict(
            "os.environ", {"OPENAI_API_BASE": "https://proxy.azure.example/v1"}
        ):
            warn_openai_base_url_override(["o3"])
        assert "route there" in capsys.readouterr().err

    def test_silent_on_official_openai_url(self, capsys):
        with self._clean_env(), patch.dict(
            "os.environ", {"OPENAI_BASE_URL": "https://api.openai.com/v1"}
        ):
            warn_openai_base_url_override(["gpt-5.6-sol"])
        assert capsys.readouterr().err == ""

    def test_silent_without_openai_models(self, capsys):
        with self._clean_env(), patch.dict(
            "os.environ", {"OPENAI_BASE_URL": "https://proxy.azure.example/v1"}
        ):
            warn_openai_base_url_override(["gemini/gemini-3.1-pro-preview", "xai/grok-4.5"])
        assert capsys.readouterr().err == ""

    def test_silent_without_override(self, capsys):
        with self._clean_env():
            warn_openai_base_url_override(["gpt-5.6-sol"])
        assert capsys.readouterr().err == ""
