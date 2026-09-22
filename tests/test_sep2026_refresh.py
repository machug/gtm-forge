"""Tests for the September 2026 model refresh: gpt-6-astra handling,
new xAI default, and Fable 5.1 temperature detection."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "gtm-forge" / "scripts"))

import models
import providers


def test_xai_default_is_grok_47(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "x")
    defaults = {name: model for name, _, model in providers.get_available_providers()}
    assert defaults["xAI"] == "xai/grok-4.7"


def test_fable_51_omits_temperature():
    assert models.claude_version("claude-fable-5-1") == (5, 1)
    assert models.is_reasoning_model("claude-fable-5-1")
    assert not models.uses_max_completion_tokens("claude-fable-5-1")


def test_gpt6_astra_is_reasoning_model():
    assert models.is_reasoning_model("gpt-6-astra")
    assert models.uses_max_completion_tokens("gpt-6-astra")
    assert models.is_reasoning_model("codex/gpt-6-astra")
    assert "gpt-6-astra" in providers.CODEX_CHATGPT_MODELS
