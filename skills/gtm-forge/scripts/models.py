"""Model calling, cost tracking, and parallel execution for gtm-forge."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
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
    ANTIGRAVITY_AVAILABLE,
    ANTIGRAVITY_PATH,
    CODEX_AVAILABLE,
    CODEX_PATH,
    DEFAULT_CODEX_REASONING,
    GEMINI_CLI_AVAILABLE,
    GEMINI_CLI_PATH,
    get_model_cost,
)

MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0

# Error substrings that retrying cannot fix: bad model id, wrong auth mode,
# rejected/revoked credentials. These are deterministic 4xx-class failures --
# retrying just burns time and spams warnings.
NON_RETRYABLE_PATTERNS = (
    "not supported when using codex with a chatgpt account",
    "invalid_request_error",
    "model_not_found",
    "does not exist or you do not have access",
    "authenticationerror",
    "invalid api key",
    "incorrect api key",
    "notfounderror",
    # Antigravity CLI deterministic failures
    "is not authenticated",
    "invalid model selection",
    # Bedrock deterministic failures (matches the spec-debate reference set)
    "model not enabled in your bedrock account",
    "invalid bedrock model id",
)

CODEX_CHATGPT_HINT = (
    "Codex is authenticated with a ChatGPT account, which only serves: "
    "gpt-5.6-sol, gpt-5.6-terra, gpt-5.6-luna, gpt-5.5 "
    "(gpt-5.4/-mini retire 2026-08-31; gpt-5.3-codex-spark needs ChatGPT Pro). "
    "For other models authenticate Codex with an API key or use the "
    "OPENAI_API_KEY litellm route (e.g. --models gpt-5.5-pro)."
)


def is_non_retryable_error(error_msg: str) -> bool:
    """Whether an error is deterministic (4xx-class) and not worth retrying."""
    lower = error_msg.lower()
    return any(p in lower for p in NON_RETRYABLE_PATTERNS)


# Anthropic models from this version up reject any temperature but 1
# (verified 2026-08-31: claude-opus-4-7/-4-8, claude-opus-5, claude-sonnet-5 and
# claude-fable-5 all raise UnsupportedParamsError on temperature=0.4; sonnet-4-6,
# opus-4-6 and haiku-4-5 still accept it).
CLAUDE_FIXED_TEMPERATURE_FROM = (4, 7)

# Matches "claude-opus-5", "claude-opus-4-8", "claude-sonnet-4-6-20250627-v1:0",
# "anthropic.claude-opus-4-7-...", "antigravity/claude-sonnet-4-6". Deliberately
# does NOT match the legacy "claude-3-5-sonnet" ordering, which is pre-4.7.
_CLAUDE_VERSION_RE = re.compile(r"claude-(?:opus|sonnet|haiku|fable)-(\d+)(?:[-.](\d+))?")


def claude_version(model: str) -> Optional[tuple[int, int]]:
    """Return (major, minor) for a Claude model id, or None if not one."""
    m = _CLAUDE_VERSION_RE.search(model.lower())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2) or 0))


def is_reasoning_model(model: str) -> bool:
    """Check if a model is a reasoning model (o-series, gpt-5, Claude 4.7+).

    Reasoning models differ from standard models:
    - They ignore or reject the temperature parameter (fixed internally)
    - Most use max_completion_tokens instead of max_tokens
    """
    model_lower = model.lower()
    if model_lower.startswith(("o1", "o3", "o4")) or any(
        f"/{p}" in model_lower for p in ("o1", "o3", "o4")
    ):
        return True
    if "gpt-5" in model_lower:
        return True
    # Anthropic Claude 4.7 and newer only accept temperature=1
    version = claude_version(model_lower)
    if version and version >= CLAUDE_FIXED_TEMPERATURE_FROM:
        return True
    return False


def uses_max_completion_tokens(model: str) -> bool:
    """Check if a model uses max_completion_tokens instead of max_tokens.

    The OpenAI-shaped reasoners do; Anthropic takes max_tokens.
    """
    if not is_reasoning_model(model):
        return False
    if claude_version(model):
        return False
    return True


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

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        # str(TimeoutExpired) embeds the full argv (prompt + document); raise a
        # clean message so document text can't trip the non-retryable classifier.
        raise RuntimeError(f"Codex CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError("Codex CLI not found in PATH")

    # Parse JSONL output to extract agent messages and structured errors.
    # Codex CLI emits API errors as `{"type":"error",...}` events on stdout
    # while stderr carries deprecation warnings and unrelated noise --
    # prefer the structured error over raw stderr.
    response_text = ""
    input_tokens = 0
    output_tokens = 0
    structured_error: Optional[str] = None

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                response_text = item.get("text", "")
        elif event_type == "turn.completed":
            usage = event.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
        elif event_type in ("error", "turn.failed"):
            # The "error" field may be a dict, a bare string, or null.
            err = event.get("error")
            msg = event.get("message") or (
                err.get("message") if isinstance(err, dict) else err
            )
            if msg:
                structured_error = msg

    if result.returncode != 0 or structured_error:
        error_msg = (
            structured_error
            or result.stderr.strip()
            or f"Codex exited with code {result.returncode}"
        )
        raise RuntimeError(f"Codex CLI failed: {error_msg}")

    if not response_text:
        raise RuntimeError("No agent message in Codex output")
    return response_text, input_tokens, output_tokens


# One-shot flag so the retirement notice doesn't repeat on every call/retry.
_gemini_retirement_warned = False


def call_gemini_cli_model(
    system_prompt: str, user_message: str, model: str, timeout: int = 600,
) -> tuple[str, int, int]:
    """Call Gemini CLI. Returns (response_text, input_tokens, output_tokens).

    Note: Gemini CLI's consumer service was retired 2026-06-18 -- prefer
    antigravity/<model> (agy CLI) or gemini/<model> (GEMINI_API_KEY).
    """
    if not GEMINI_CLI_AVAILABLE:
        raise RuntimeError(
            "Gemini CLI not found. Note: Gemini CLI was retired for consumer "
            "accounts on 2026-06-18 -- use antigravity/<model> (agy CLI) or "
            "gemini/<model> (GEMINI_API_KEY) instead."
        )

    global _gemini_retirement_warned
    if not _gemini_retirement_warned:
        _gemini_retirement_warned = True
        print(
            "Warning: Gemini CLI consumer service was retired 2026-06-18 in favor of "
            "Antigravity CLI. If this call fails, switch to antigravity/<model> "
            "(agy CLI) or gemini/<model> (GEMINI_API_KEY).",
            file=sys.stderr,
        )

    actual_model = model.split("/", 1)[1] if "/" in model else model
    full_prompt = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER REQUEST:\n{user_message}"

    cmd = [GEMINI_CLI_PATH, "-m", actual_model, "-y"]
    try:
        result = subprocess.run(cmd, input=full_prompt, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Gemini CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError("Gemini CLI not found in PATH")

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


def resolve_antigravity_model(model: str) -> Optional[str]:
    """Extract the agy model slug from an antigravity/<slug> model string.

    `agy --model` accepts slugs exactly as listed by `agy models`
    (e.g. gemini-3.1-pro-high, claude-sonnet-4-6, gpt-oss-120b-medium).
    Returns None for a bare "antigravity" (use agy's default model).
    """
    slug = model.split("/", 1)[1] if "/" in model else ""
    return slug or None


def call_antigravity_model(
    system_prompt: str, user_message: str, model: str, timeout: int = 600,
) -> tuple[str, int, int]:
    """Call Antigravity CLI (agy) in headless print mode using Google account auth.

    Sign in once interactively (`agy`) before headless use -- print mode reuses
    cached credentials and cannot complete the OAuth flow itself.

    Returns (response_text, input_tokens, output_tokens). Token counts come
    from agy JSON metadata when present, else estimated.
    """
    if not ANTIGRAVITY_AVAILABLE:
        raise RuntimeError(
            "Antigravity CLI not found. Install with: "
            "curl -fsSL https://antigravity.google/cli/install.sh | bash "
            "-- then run `agy` once to sign in."
        )

    display_model = resolve_antigravity_model(model)
    full_prompt = f"SYSTEM INSTRUCTIONS:\n{system_prompt}\n\nUSER REQUEST:\n{user_message}"

    cmd = [
        ANTIGRAVITY_PATH,
        "-p", full_prompt,
        "--output-format", "json",
        "--print-timeout", f"{timeout}s",
    ]
    if display_model:
        cmd.extend(["--model", display_model])

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout + 30,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Antigravity CLI timed out after {timeout}s")
    except FileNotFoundError:
        raise RuntimeError("Antigravity CLI not found in PATH")

    stdout = result.stdout.strip()

    # agy prints an interactive OAuth prompt when credentials are missing --
    # detect its fixed prompt strings, not URL fragments (which could appear
    # in legitimate model output).
    if (
        "Waiting for authentication" in result.stdout
        or "paste the authorization code" in result.stdout
    ):
        raise RuntimeError(
            "Antigravity CLI is not authenticated. Run `agy` interactively once "
            "to complete Google sign-in, then retry."
        )

    if result.returncode != 0:
        error_msg = (
            result.stderr.strip()
            or stdout
            or f"Antigravity CLI exited with code {result.returncode}"
        )
        raise RuntimeError(f"Antigravity CLI failed: {error_msg}")

    response_text = ""
    input_tokens = 0
    output_tokens = 0

    # JSON output is a single object; schema may evolve, so probe common keys.
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        status = payload.get("status", "")
        if status and status != "SUCCESS":
            raise RuntimeError(
                f"Antigravity CLI returned status {status}: "
                f"{payload.get('error') or payload.get('response') or stdout[:200]}"
            )
        for key in ("response", "result", "text", "output", "message"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                response_text = value.strip()
                break
        usage = payload.get("usage") or payload.get("metadata") or {}
        if isinstance(usage, dict):
            input_tokens = int(usage.get("input_tokens", 0) or 0)
            output_tokens = int(usage.get("output_tokens", 0) or 0)

    if not response_text and payload is None:
        # Fall back to raw stdout only when it wasn't JSON at all
        # (e.g. --output-format ignored by an older agy)
        response_text = stdout

    if not response_text:
        raise RuntimeError("No response text in Antigravity CLI output: " + stdout[:200])

    if not input_tokens:
        input_tokens = len(full_prompt) // 4
    if not output_tokens:
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
    Handles codex/, antigravity/, gemini-cli/, foundry/, and standard litellm models.
    """
    if model.startswith("codex/"):
        return call_codex_model(system_prompt, user_message, model, timeout=timeout)

    if model == "antigravity" or model.startswith("antigravity/"):
        return call_antigravity_model(system_prompt, user_message, model, timeout=timeout)

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
    if uses_max_completion_tokens(model):
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
    if not is_reasoning_model(model):
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

    Retries transient failures with exponential backoff; deterministic errors
    (unknown model, wrong auth mode, bad credentials) fail fast. Codex
    ChatGPT-account model rejections get an actionable hint appended.

    Raises RuntimeError on final failure.
    """
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return _call_model_raw(model, system_prompt, user_message, timeout, max_tokens)
        except Exception as e:
            last_error = str(e)
            if "not supported when using codex with a chatgpt account" in last_error.lower():
                last_error = f"{last_error}\n  Hint: {CODEX_CHATGPT_HINT}"
            if is_non_retryable_error(last_error):
                print(
                    f"Error: {model} failed (non-retryable): {last_error}",
                    file=sys.stderr,
                )
                break
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
