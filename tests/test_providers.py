"""Basic tests for gtm-forge provider detection."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent.parent / "skills" / "gtm-forge" / "scripts"))


def test_get_model_cost_returns_dict():
    """Cost lookup should return a dict with input/output keys."""
    from providers import get_model_cost
    cost = get_model_cost("gpt-5.4")
    assert "input" in cost
    assert "output" in cost


def test_cli_tools_are_free():
    """Codex and Gemini CLI tools should report zero cost."""
    from providers import get_model_cost
    for prefix in ("codex/gpt-5.3-codex", "gemini-cli/gemini-3.1-pro"):
        cost = get_model_cost(prefix)
        assert cost["input"] == 0.0
        assert cost["output"] == 0.0


def test_unknown_model_returns_default():
    """Unknown models should return the default cost."""
    from providers import get_model_cost, DEFAULT_COST
    cost = get_model_cost("totally-fake-model-xyz")
    assert cost == DEFAULT_COST


def test_detect_available_providers_with_no_keys():
    """With no API keys set, should return empty or minimal provider list."""
    env_vars_to_clear = [
        "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
        "XAI_API_KEY", "AZURE_AI_API_KEY", "MISTRAL_API_KEY",
        "GROQ_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY",
    ]
    with patch.dict(os.environ, {k: "" for k in env_vars_to_clear}, clear=False):
        from providers import detect_available_providers
        providers = detect_available_providers()
        # Should be a list (may include CLI tools if installed)
        assert isinstance(providers, list)
