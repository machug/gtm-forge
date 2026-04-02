"""Model calling, cost tracking, and parallel execution for gtm-forge."""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

os.environ["LITELLM_LOG"] = "ERROR"

try:
    import litellm
    from litellm import completion

    litellm.suppress_debug_info = True
except ImportError:
    print(
        "Error: litellm package not installed. Run: pip install litellm",
        file=sys.stderr,
    )
    sys.exit(1)

from providers import (
    CODEX_AVAILABLE,
    CODEX_PATH,
    DEFAULT_CODEX_REASONING,
    GEMINI_CLI_AVAILABLE,
    GEMINI_CLI_PATH,
    get_model_cost,
)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0


def is_reasoning_model(model: str) -> bool:
    """Check if a model is a reasoning model (o-series, gpt-5).

    Reasoning models differ from standard models:
    - They ignore the temperature parameter (fixed internally)
    - They use max_completion_tokens instead of max_tokens
    """
    model_lower = model.lower()
    if model_lower.startswith(("o1", "o3", "o4")) or any(
        f"/{p}" in model_lower for p in ("o1", "o3", "o4")
    ):
        return True
    if "gpt-5" in model_lower:
        return True
    return False


@dataclass
class CritiqueResponse:
    """Response from a GTM critique model."""

    model: str
    response: str
    scores: dict[str, int]  # {dimension: score 1-10}
    issues: list[dict]  # [{dimension, severity, issue, suggestion}]
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


@dataclass
class GenericResponse:
    """Response from a generic model call (research, counter-pitch, synthesis)."""

    model: str
    response: str
    error: Optional[str] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


@dataclass
class CostTracker:
    """Track token usage and costs across model calls."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    by_model: dict = field(default_factory=dict)

    def add(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Add usage for a model call and return the cost."""
        costs = get_model_cost(model)
        cost = (input_tokens / 1_000_000 * costs["input"]) + (
            output_tokens / 1_000_000 * costs["output"]
        )

        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost

        if model not in self.by_model:
            self.by_model[model] = {"input_tokens": 0, "output_tokens": 0, "cost": 0.0}
        self.by_model[model]["input_tokens"] += input_tokens
        self.by_model[model]["output_tokens"] += output_tokens
        self.by_model[model]["cost"] += cost

        return cost

    def summary(self) -> str:
        """Generate cost summary string."""
        lines = ["", "=== Cost Summary ==="]
        lines.append(
            f"Total tokens: {self.total_input_tokens:,} in / {self.total_output_tokens:,} out"
        )
        lines.append(f"Total cost: ${self.total_cost:.4f}")
        if len(self.by_model) > 1:
            lines.append("")
            lines.append("By model:")
            for model, data in self.by_model.items():
                lines.append(
                    f"  {model}: ${data['cost']:.4f} ({data['input_tokens']:,} in / {data['output_tokens']:,} out)"
                )
        return "\n".join(lines)

    def breakdown_str(self) -> str:
        """Short cost breakdown for reports."""
        parts = []
        for model, data in self.by_model.items():
            short_name = model.split("/")[-1] if "/" in model else model
            parts.append(f"{short_name}: ${data['cost']:.4f}")
        return ", ".join(parts) if parts else "N/A"


# Global cost tracker
cost_tracker = CostTracker()


def parse_critique_json(response_text: str) -> tuple[dict[str, int], list[dict]]:
    """Parse JSON critique response into scores and issues.

    Expects JSON with:
    {
        "scores": {"premise_validity": 7, ...},
        "issues": [{"dimension": "...", "severity": "...", "issue": "...", "suggestion": "..."}, ...]
    }

    Returns (scores, issues). Falls back to empty dicts on parse failure.
    """
    # Try to find JSON block in response (may be wrapped in markdown code fences)
    text = response_text.strip()
    if "```json" in text:
        start = text.find("```json") + 7
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()
    elif "```" in text:
        start = text.find("```") + 3
        end = text.find("```", start)
        if end > start:
            text = text[start:end].strip()

    # Find the outermost JSON object
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        text = text[brace_start:brace_end + 1]

    try:
        data = json.loads(text)
        scores = {}
        for k, v in data.get("scores", {}).items():
            try:
                scores[k] = int(v)
            except (ValueError, TypeError):
                scores[k] = 0
        issues = data.get("issues", [])
        if not isinstance(issues, list):
            issues = []
        return scores, issues
    except (json.JSONDecodeError, AttributeError):
        return {}, []


def call_foundry_model(
    system_prompt: str, user_message: str, model: str, timeout: int = 600,
) -> tuple[str, int, int]:
    """Call Azure AI Foundry v2 using the azure-ai-inference SDK.

    Returns (response_text, input_tokens, output_tokens).
    """
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage
    from azure.core.credentials import AzureKeyCredential

    api_key = os.environ.get("AZURE_AI_API_KEY")
    api_base = os.environ.get("AZURE_AI_API_BASE", "")

    if not api_key:
        raise ValueError("AZURE_AI_API_KEY environment variable not set")

    endpoint = api_base.rstrip("/")
    if not endpoint.endswith("/models"):
        parts = endpoint.split(".services.ai.azure.com")
        if len(parts) == 2:
            endpoint = parts[0] + ".services.ai.azure.com/models"
        else:
            endpoint = endpoint + "/models"

    deployment_name = model.split("/", 1)[1] if "/" in model else model

    client = ChatCompletionsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(api_key),
    )

    response = client.complete(
        messages=[
            SystemMessage(content=system_prompt),
            UserMessage(content=user_message),
        ],
        model=deployment_name,
    )

    content = response.choices[0].message.content or ""
    input_tokens = response.usage.prompt_tokens if response.usage else 0
    output_tokens = response.usage.completion_tokens if response.usage else 0

    return content, input_tokens, output_tokens


def call_codex_model(
    system_prompt: str, user_message: str, model: str,
    reasoning_effort: str = DEFAULT_CODEX_REASONING, timeout: int = 600,
) -> tuple[str, int, int]:
    """Call Codex CLI. Returns (response_text, input_tokens, output_tokens)."""
    if not CODEX_AVAILABLE:
        raise RuntimeError("Codex CLI not found. Install: npm install -g @openai/codex")

    actual_model = model.split("/", 1)[1] if "/" in model else model
    full_prompt = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER REQUEST:\n{user_message}"

    cmd = [
        CODEX_PATH, "exec", "--json", "--full-auto", "--skip-git-repo-check",
        "--model", actual_model,
        "-c", f'model_reasoning_effort="{reasoning_effort}"',
        full_prompt,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"Codex CLI failed: {result.stderr.strip()}")

    response_text = ""
    input_tokens = 0
    output_tokens = 0

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if item.get("type") == "agent_message":
                    response_text = item.get("text", "")
            if event.get("type") == "turn.completed":
                usage = event.get("usage", {})
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
        except json.JSONDecodeError:
            continue

    if not response_text:
        raise RuntimeError("No agent message in Codex output")
    return response_text, input_tokens, output_tokens


def call_gemini_cli_model(
    system_prompt: str, user_message: str, model: str, timeout: int = 600,
) -> tuple[str, int, int]:
    """Call Gemini CLI. Returns (response_text, input_tokens, output_tokens)."""
    if not GEMINI_CLI_AVAILABLE:
        raise RuntimeError("Gemini CLI not found. Install: npm install -g @google/gemini-cli")

    actual_model = model.split("/", 1)[1] if "/" in model else model
    full_prompt = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER REQUEST:\n{user_message}"

    cmd = [GEMINI_CLI_PATH, "-m", actual_model, "-y"]
    result = subprocess.run(cmd, input=full_prompt, capture_output=True, text=True, timeout=timeout)

    if result.returncode != 0:
        raise RuntimeError(f"Gemini CLI failed: {result.stderr.strip()}")

    response_text = result.stdout.strip()
    skip_prefixes = ("Loaded cached", "Server ", "Loading extension")
    lines = [l for l in response_text.split("\n") if not any(l.startswith(p) for p in skip_prefixes)]
    response_text = "\n".join(lines).strip()

    if not response_text:
        raise RuntimeError("No response from Gemini CLI")

    input_tokens = len(full_prompt) // 4
    output_tokens = len(response_text) // 4
    return response_text, input_tokens, output_tokens


def _call_model_raw(
    model: str,
    system_prompt: str,
    user_message: str,
    timeout: int = 600,
    max_tokens: int = 12000,
) -> tuple[str, int, int]:
    """Low-level model call that routes to the correct backend.

    Returns (response_text, input_tokens, output_tokens).
    Handles codex/, gemini-cli/, foundry/, and standard litellm models.
    """
    if model.startswith("codex/"):
        return call_codex_model(system_prompt, user_message, model, timeout=timeout)

    if model.startswith("gemini-cli/"):
        return call_gemini_cli_model(system_prompt, user_message, model, timeout=timeout)

    if model.startswith("foundry/"):
        return call_foundry_model(system_prompt, user_message, model, timeout=timeout)

    # Standard LiteLLM path
    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "timeout": timeout,
    }
    if is_reasoning_model(model):
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = 0.4

    response = completion(**kwargs)
    content = response.choices[0].message.content or ""
    in_tok = response.usage.prompt_tokens if response.usage else 0
    out_tok = response.usage.completion_tokens if response.usage else 0

    return content, in_tok, out_tok


def _call_with_retry(
    model: str,
    system_prompt: str,
    user_message: str,
    timeout: int = 600,
    max_tokens: int = 12000,
) -> tuple[str, int, int]:
    """Call a model with retry logic. Returns (response_text, input_tokens, output_tokens).

    Raises RuntimeError on final failure.
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return _call_model_raw(model, system_prompt, user_message, timeout, max_tokens)
        except Exception as e:
            last_error = str(e)
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                print(
                    f"Warning: {model} failed (attempt {attempt + 1}/{MAX_RETRIES}): {last_error}. Retrying in {delay:.1f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
            else:
                print(
                    f"Error: {model} failed after {MAX_RETRIES} attempts: {last_error}",
                    file=sys.stderr,
                )
    raise RuntimeError(last_error)


def call_single_model_critique(
    model: str,
    system_prompt: str,
    user_message: str,
    timeout: int = 600,
) -> CritiqueResponse:
    """Send a GTM document to a single model for adversarial critique."""
    try:
        content, in_tok, out_tok = _call_with_retry(model, system_prompt, user_message, timeout)
        scores, issues = parse_critique_json(content)
        cost = cost_tracker.add(model, in_tok, out_tok)
        return CritiqueResponse(
            model=model, response=content, scores=scores, issues=issues,
            input_tokens=in_tok, output_tokens=out_tok, cost=cost,
        )
    except RuntimeError as e:
        return CritiqueResponse(
            model=model, response="", scores={}, issues=[], error=str(e),
        )


def call_single_model_generic(
    model: str,
    system_prompt: str,
    user_message: str,
    timeout: int = 600,
    max_tokens: int = 12000,
) -> GenericResponse:
    """Send a prompt to a single model and return raw response."""
    try:
        content, in_tok, out_tok = _call_with_retry(
            model, system_prompt, user_message, timeout, max_tokens,
        )
        cost = cost_tracker.add(model, in_tok, out_tok)
        return GenericResponse(
            model=model, response=content,
            input_tokens=in_tok, output_tokens=out_tok, cost=cost,
        )
    except RuntimeError as e:
        return GenericResponse(model=model, response="", error=str(e))


def critique_parallel(
    models: list[str],
    system_prompt: str,
    user_message: str,
    timeout: int = 600,
) -> list[CritiqueResponse]:
    """Call multiple models in parallel for GTM critique."""
    if not models:
        return []
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as executor:
        future_to_model = {
            executor.submit(
                call_single_model_critique, model, system_prompt, user_message, timeout,
            ): model
            for model in models
        }
        for future in concurrent.futures.as_completed(future_to_model):
            results.append(future.result())
    return results


def generic_parallel(
    models: list[str],
    system_prompt: str,
    user_message: str,
    timeout: int = 600,
    max_tokens: int = 12000,
) -> list[GenericResponse]:
    """Call multiple models in parallel for generic prompts (research, counter-pitch, etc.)."""
    if not models:
        return []
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(models)) as executor:
        future_to_model = {
            executor.submit(
                call_single_model_generic, model, system_prompt, user_message, timeout, max_tokens,
            ): model
            for model in models
        }
        for future in concurrent.futures.as_completed(future_to_model):
            results.append(future.result())
    return results
