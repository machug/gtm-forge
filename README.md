# gtm-forge

Build, validate, and stress-test Go-To-Market strategies for enterprise managed services.

## What it does

GTM Forge is a Claude Code skill that takes a GTM strategy document through a rigorous multi-stage pipeline:

```
research --> draft --> verify --> stress-test --> debate --> refine
```

**Built for enterprise B2B managed services**, not SaaS startups. Understands vendor-funded models, multi-vendor positioning, partner dynamics, and CISO-level buying decisions.

## Pipeline

| Stage | What happens |
|-------|-------------|
| **Research** | Market sizing, competitive landscape, vendor funding programs via web search and MCP |
| **Draft** | Interview-driven GTM generation with structured sections |
| **Verify** | Multi-LLM triage + source-grounded verification of every vendor claim |
| **Stress-test** | Adversarial critique scoring 8 dimensions (premise, ICP, moat, commercial, technical, execution, pricing, timing) |
| **Debate** | Multi-LLM adversarial refinement until convergence |
| **Counter-pitch** | Models role-play competitors to find positioning weaknesses |
| **Funding** | Research vendor partner programs, grants, co-sell incentives |

## Install

```bash
npx skills add machug/gtm-forge
```

Or manually clone and add to your Claude Code settings.

## Requirements

- Python 3.10+
- `pip install litellm`
- API key for at least one LLM provider (or Codex/Gemini CLI)

### Supported providers

| Provider | Env var | Example models |
|----------|---------|----------------|
| OpenAI | `OPENAI_API_KEY` | `gpt-5.6-sol`, `gpt-5.5-pro` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5` |
| Google | `GEMINI_API_KEY` | `gemini/gemini-3.1-pro-preview`, `gemini/gemini-3.6-flash` |
| xAI | `XAI_API_KEY` | `xai/grok-4.5` |
| Azure AI | `AZURE_AI_API_KEY` | `foundry/claude-opus-5` |
| Mistral | `MISTRAL_API_KEY` | `mistral/mistral-large` |
| Deepseek | `DEEPSEEK_API_KEY` | `deepseek/deepseek-v4-pro` |
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/openai/gpt-5.5-pro` |
| ZAI (GLM) | `ZAI_API_KEY` | `zai/glm-5.2` |
| Moonshot | `MOONSHOT_API_KEY` | `moonshot/kimi-k3` |
| MiniMax | `MINIMAX_API_KEY` | `minimax/MiniMax-M3` |
| Codex CLI | (ChatGPT subscription) | `codex/gpt-5.6-sol`, `codex/gpt-5.5` |
| Antigravity CLI | (Google account) | `antigravity/gemini-3.1-pro-high` |
| Gemini CLI | (retired 2026-06-18) | use `antigravity/` or `gemini/` instead |

Note: ChatGPT-account Codex serves only the ChatGPT lineup (gpt-5.6-sol/terra/luna, gpt-5.5;
gpt-5.4 and gpt-5.4-mini until they retire 2026-08-31). Other models (gpt-5.3-codex,
gpt-5.5-pro) need Codex API-key auth or the `OPENAI_API_KEY` route.

## Usage

Invoke via Claude Code:

```
/gtm-forge
```

Or use CLI tools directly:

```bash
cd skills/gtm-forge/scripts

# Check providers
python3 forge.py providers

# Extract claims from existing GTM doc
python3 forge.py extract path/to/gtm.md

# Run adversarial critique
python3 forge.py critique --models gpt-5.6-sol,gemini/gemini-3.1-pro-preview --document gtm.md

# Generate competitor counter-pitches
python3 forge.py counter-pitch --models gpt-5.6-sol --document gtm.md --competitors "Deloitte,Accenture"

# Research funding programs
python3 forge.py research --query "Cisco partner funding AI security 2026"

# Full debate loop
python3 forge.py debate --models gpt-5.6-sol,xai/grok-4.5 --document gtm.md --rounds 3
```

## Author

Hugh McIntyre ([hughtec.com](https://hughtec.com)) - machug

## License

MIT
