---
name: gtm-forge
description: Build, validate, and stress-test Go-To-Market strategies for enterprise managed services. Multi-LLM adversarial critique, vendor claim verification, funding research, and competitive counter-pitches. Use when user says "GTM", "go-to-market", "managed service strategy", "gtm-forge", or wants to build/review a GTM.
allowed-tools: Bash, Read, Write, Edit, Agent, AskUserQuestion, WebFetch, WebSearch, Grep, Glob, mcp__microsoft_docs_mcp__microsoft_docs_search, mcp__microsoft_docs_mcp__microsoft_docs_fetch, mcp__microsoft_docs_mcp__microsoft_code_sample_search, mcp__plugin_context7_context7__resolve-library-id, mcp__plugin_context7_context7__query-docs
---

# GTM Forge: Enterprise Managed Service GTM Builder & Stress-Tester

**If the user asks to see the banner, NFO, or splash screen, display the following:**

```
                     ▄▄                          ▄▄
           ▄▄▄▄▄▄▄▄██▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄██▄▄▄▄▄▄▄▄
          ▐░░░▒▒▒▓▓                                ▓▓▒▒▒░░░▌
          ▐░     ████ █████ █   █                       ░▌
          ▐░     █      █   ██ ██                       ░▌
          ▐░     █ ██   █   █ █ █                       ░▌
          ▐░     █  █   █   █   █                       ░▌
          ▐░     ████   █   █   █                       ░▌
          ▐░                                            ░▌
          ▐░     ████ ████ ████  ████ ████              ░▌
          ▐░     █    █  █ █  █ █    █                  ░▌
          ▐░     ███  █  █ ████ █ ██ ███                ░▌
          ▐░     █    █  █ █ █  █  █ █                  ░▌
          ▐░     █    ████ █  █  ████ ████              ░▌
          ▐░░░▒▒▒▓▓                                ▓▓▒▒▒░░░▌
           ▀▀▀▀▀▀▀▀██▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀██▀▀▀▀▀▀▀▀
                     ▀▀                          ▀▀
          ╔══════════════════════════════════════════════════╗
          ║              RELEASE INFORMATION                 ║
          ╠══════════════════════════════════════════════════╣
          ║                                                  ║
          ║  Skill.......: gtm-forge                         ║
          ║  Author......: machug          (hughtec.com)     ║
          ║  Version.....: 1.4.0                             ║
          ║  Released....: 2026                              ║
          ║  License.....: MIT                               ║
          ║  Requires....: Python 3.10+ (deps auto-install)  ║
          ║                                                  ║
          ╠══════════════════════════════════════════════════╣
          ║               PIPELINE OVERVIEW                  ║
          ╠══════════════════════════════════════════════════╣
          ║                                                  ║
          ║  research --> draft --> verify --> stress-test    ║
          ║      --> debate --> counter-pitch --> refine      ║
          ║                                                  ║
          ║  Enterprise managed service GTM builder.          ║
          ║  Multi-LLM adversarial validation.               ║
          ║  Vendor claims verified against official docs.   ║
          ║  N models critique. 1 GTM ships.                 ║
          ║                                                  ║
          ╚══════════════════════════════════════════════════╝
```

## Overview

Build and validate Go-To-Market strategies for enterprise managed services through a multi-stage pipeline:

1. **Research** -- Market sizing, competitive landscape, vendor funding programs
2. **Draft** -- Interview-driven GTM generation (or ingest existing GTM doc)
3. **Verify** -- Multi-LLM triage + source-grounded verification of vendor claims
4. **Stress-test** -- Adversarial critique scoring 8 dimensions
5. **Debate** -- Multi-LLM adversarial refinement until convergence
6. **Counter-pitch** -- Models role-play competitors to find positioning gaps
7. **Funding research** -- Search for vendor partner programs, grants, co-sell incentives
8. **Refine** -- Synthesize all feedback into final GTM with confidence scores

**Built for enterprise B2B managed services.** Understands vendor-funded assessment models, multi-vendor positioning, partner dynamics, and CISO-level buying decisions.

## Scripts Location

All scripts are in the skill's `scripts/` directory (relative to the plugin root):
```
skills/gtm-forge/scripts/
├── forge.py       # Main orchestrator + CLI
├── models.py      # LiteLLM calls, parallel execution, cost tracking
├── prompts.py     # GTM-specific prompt templates
├── providers.py   # Provider config + cost tracking tables
└── sources.py     # Vendor source registry + MCP detection
```

## Setup: resolve the interpreter first

**Run this once at the start of every session, before any other command in this skill.** It prints the path to a Python interpreter that can import `litellm`, installing the dependencies into a cached virtual environment on first use.

```bash
GTM_FORGE_PY=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts/bootstrap.sh)
```

Then use `"$GTM_FORGE_PY"` everywhere this skill writes `python3`. For example:

```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts && "$GTM_FORGE_PY" forge.py providers
```

The script prints only the interpreter path on stdout, so it is safe to capture. Progress messages go to stderr. It reuses an existing environment on later runs, uses `uv` when available and falls back to `python3 -m venv`, and rebuilds automatically if the environment breaks.

Do not run `pip install litellm` by hand, and do not build your own virtual environment. If `bootstrap.sh` fails, report its stderr rather than improvising an install.

The environment lives in `${XDG_CACHE_HOME:-~/.cache}/gtm-forge/venv`, deliberately outside the plugin directory: plugin installs are version-keyed, so an environment stored beside the code would be rebuilt on every plugin update. Override the location with `GTM_FORGE_VENV`.

**Checking the installed version:** `litellm` has no `__version__` attribute. Use `importlib.metadata.version("litellm")`. Reading `litellm.__version__` raises `AttributeError` and makes a working install look broken.

## Claude model behavior

Claude Opus 4.7 and newer — including Claude Opus 5, Sonnet 5, and Fable 5 — accept only `temperature=1`. `models.py` detects these and omits the parameter, and keeps `max_tokens` rather than `max_completion_tokens` for them. Claude Sonnet 4.6, Opus 4.6, and Haiku 4.5 still accept a temperature and are unchanged.

## Workflow

Follow these steps in order. Each step has a user checkpoint. Do NOT skip ahead without confirmation.

### Step 0: PREFLIGHT CHECK

Before starting, check what LLM providers are available:
```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts && python3 forge.py providers
```

**If no external providers are found** (no API keys set, no CLI tools installed), warn the user:

> **Warning: No external LLM providers detected.** GTM Forge works best with 2-3 independent models for adversarial critique and debate. Without external models, I'll provide my own critique, but you lose the independent perspectives that catch blind spots and groupthink.
>
> **Recommended setup (pick one):**
> - Set `OPENROUTER_API_KEY` for access to multiple providers with a single key
> - Or set API keys for 2+ providers (e.g. `OPENAI_API_KEY`, `GEMINI_API_KEY`, `XAI_API_KEY`)
> - Or set `AZURE_AI_API_KEY` + `AZURE_AI_API_BASE` for Azure AI Foundry models
> - Or install Codex CLI (`npm install -g @openai/codex`) or Antigravity CLI (`curl -fsSL https://antigravity.google/cli/install.sh | bash`)

Then ask: "Continue anyway with single-model critique, or set up providers first?"

**IMPORTANT -- no simulated diversity:** If no external LLMs are available, do NOT launch subagents that role-play different perspectives. That is not real independent verification. Instead, provide your own thorough critique and be transparent that multi-model adversarial review was skipped.

### Step 1: MODE SELECTION

Ask the user which mode they want:

> **GTM Forge can operate in several modes:**
>
> **A) Build from scratch** -- Interview-driven GTM creation. I'll ask about your service, market, positioning, then draft a complete GTM.
>
> **B) Review existing GTM** -- Provide an existing GTM document. I'll run the full verification + stress-test + debate pipeline against it.
>
> **C) Research only** -- Market research, competitive landscape, and/or vendor funding program discovery. No GTM drafting.
>
> **D) Targeted section** -- Run a specific pipeline stage against an existing doc (verify claims, run competitive counter-pitches, research funding, etc.)

### Step 2: CONTEXT GATHERING (Mode A) or INGEST (Mode B/D)

**Mode A -- Build from scratch:**

Conduct a structured interview using AskUserQuestion. Cover ALL of these topics:

**1. Service Definition**
- What is the managed service? What does it do for the client?
- What technology stack does it use? (vendor products, open-source tools, proprietary)
- What operational activities does your team perform on behalf of the client?
- What is the service NOT? (scope boundaries)

**2. Market & Demand**
- Who is the buyer? (title, org size, industry, existing tech stack)
- What pain point does this solve? What happens if they do nothing?
- How do they solve this problem today? (status quo is the real competitor)
- Why now? What has changed that makes this timely?
- Is there evidence of demand? (inbound requests, RFP patterns, analyst coverage)

**3. Competitive Landscape**
- Who else offers something similar? (Big 4, other MSSPs, vendor direct, DIY)
- What is your actual moat? (not "we're better" -- structural advantages)
- What would a competitor say about your offering?

**4. Vendor & Partner Dynamics**
- Which vendors' products does this service wrap?
- Are any vendors providing funding, co-sell incentives, or subsidized assessments?
- What's the vendor's motivation? (pipeline generation, adoption, churn reduction)
- Any exclusivity or preferred partner status?

**5. Commercial Model**
- How is this priced? (per-user, flat-rate, consumption-based)
- What does the client already own vs. what's new licensing?
- What's the funding model? (who pays for what, vendor subsidies)
- What are target margins?

**6. Delivery Model**
- Who delivers? (team location, skillsets, capacity)
- What's the implementation timeline?
- What does ongoing operations look like?
- How does this scale? (1 client vs 20 clients)

**7. Go-to-Market Motion**
- How do you find clients? (existing relationships, outbound, events, vendor referrals)
- What's the land motion? (assessment, pilot, PoC)
- What's the expand motion? (assessment to implementation to managed service)
- What's the internal selling motion? (who approves this internally)

After the interview, synthesize into a structured GTM document and present for review.

**Mode B/D -- Ingest existing document:**

1. Ask the user for the document path
2. Read the document using the Read tool
3. Confirm: "I've read the GTM document. Ready to proceed with [verification/stress-test/debate]?"

### Step 3: MARKET RESEARCH

Use WebSearch to research:

1. **Market sizing** -- Search for market size, growth projections, analyst reports for the service category
2. **Competitive landscape** -- Search for competitors, their offerings, pricing where available
3. **Vendor capabilities** -- Verify key vendor product claims against official docs
4. **Regulatory drivers** -- Search for regulatory requirements driving demand (EU AI Act, ISO 42001, etc.)

For Microsoft claims, use the MCP tools:
- `microsoft_docs_search` for initial discovery
- `microsoft_docs_fetch` for deep verification

For other vendors, use WebSearch with targeted queries:
- Cisco: `site:cisco.com` or `site:blogs.cisco.com`
- Cyera: `site:cyera.com`
- ServiceNow: `site:servicenow.com` or `site:docs.servicenow.com`
- Palo Alto: `site:paloaltonetworks.com`

Present research findings to user before proceeding.

### Step 4: VENDOR CLAIM VERIFICATION

Extract all verifiable claims from the GTM document and verify them.

1. **Extract claims** -- Identify every factual claim about vendor capabilities, pricing, licensing, integrations, compliance certifications, market statistics
   ```bash
   cd ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts && python3 forge.py extract <file>
   ```

2. **Present claim list** (User Checkpoint):
   ```
   | # | Category | Claim | Vendor | Section |
   |---|----------|-------|--------|---------|
   ```
   Ask: "Review this claim list. Remove any you don't need verified, add any I missed."

3. **Multi-LLM triage** -- Send claims to 2-3 models for independent assessment:
   ```bash
   cd ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts && python3 forge.py triage claims.json --models <model1>,<model2> --document <file>
   ```
   - All models CONFIDENT = model-verified (skip deep verification)
   - Any model UNCERTAIN or SUSPECT = flagged for deep verification

4. **Deep verification** of flagged claims against authoritative sources:
   - Microsoft claims: `microsoft_docs_search` / `microsoft_docs_fetch` MCP tools
   - Other vendors: WebSearch with vendor-specific site prefixes
   - Market statistics: WebSearch for analyst reports, press releases
   - Pricing: WebSearch for official pricing pages

5. **Verification report** with verdicts:
   - **CONFIRMED** -- Source directly supports the claim
   - **NUANCED** -- Substantively correct but imprecise or overstated
   - **INCORRECT** -- Source contradicts the claim
   - **OUTDATED** -- Was true but has changed
   - **UNCONFIRMED** -- Insufficient evidence

### Step 5: ADVERSARIAL STRESS-TEST

Send the GTM to selected models for adversarial critique. Each model scores 8 dimensions:

```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts && python3 forge.py critique --models <model_list> --document <file>
```

**Scoring Dimensions (1-10):**

| # | Dimension | Question |
|---|-----------|----------|
| 1 | Premise validity | Is there real, evidenced demand? Or is this a solution looking for a problem? |
| 2 | ICP clarity | Is the target client real, reachable, and big enough to build a practice around? |
| 3 | Competitive differentiation | What's the structural moat? Would a competitor take 6 months or 6 years to replicate? |
| 4 | Commercial viability | Does the funding model work? Are margins realistic? Does the unit economics hold? |
| 5 | Technical accuracy | Are vendor capability claims correct? Any overstatements or gaps? |
| 6 | Execution feasibility | Can this team, with these resources, actually deliver this? |
| 7 | Pricing & packaging | Are the tiers logical? Does the land-expand motion work? |
| 8 | Market timing | Why now? What has changed? Is the window opening or closing? |

**You (Claude) must also provide your own independent critique.** Do not just aggregate model outputs. Provide your own scores and reasoning, then synthesize.

Present results:
```
                ADVERSARIAL CRITIQUE SCORECARD
  ════════════════════════════════════════════════════
  Dimension              | Model A | Model B | Claude | Avg
  ─────────────────────────────────────────────────────
  Premise validity       |    8    |    7    |    8   | 7.7
  ICP clarity            |    6    |    7    |    7   | 6.7
  Competitive moat       |    5    |    6    |    5   | 5.3
  Commercial viability   |    7    |    6    |    7   | 6.7
  Technical accuracy     |    8    |    8    |    9   | 8.3
  Execution feasibility  |    7    |    7    |    7   | 7.0
  Pricing & packaging    |    6    |    7    |    6   | 6.3
  Market timing          |    8    |    8    |    8   | 8.0
  ─────────────────────────────────────────────────────
  OVERALL                |   6.9   |   7.0   |   7.1  | 7.0
  ════════════════════════════════════════════════════

  Issues Found: X
  Critical (score < 5): Y
  Needs Work (score 5-6): Z
```

For any dimension scoring below 7, present the specific issues and ask the user whether to address them.

### Step 6: COMPETITIVE COUNTER-PITCHES

For each competitor listed in the GTM, have a model role-play as that competitor's practice lead and write their counter-pitch:

```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts && python3 forge.py counter-pitch --models <model> --document <file> --competitors "Deloitte,Accenture,PwC"
```

Each counter-pitch answers:
- "Why would a client choose us over this offering?"
- "What would we say in a competitive bake-off?"
- "Where is this offering weakest?"

Present counter-pitches and ask: "Any positioning changes needed based on what competitors would say?"

### Step 7: FUNDING RESEARCH

Research vendor partner programs, grants, and co-sell incentives:

1. **Identify vendors** in the GTM (e.g., Cisco, Microsoft, Cyera)
2. **Search for funding programs** using WebSearch:
   - `"[vendor] partner funding program [year]"`
   - `"[vendor] co-sell incentive managed service"`
   - `"[vendor] partner grant AI security"`
   - `"[vendor] partner demo fund assessment"`
3. **Search for partner portal/program pages:**
   - Cisco: Partner programs, Cisco Black Belt, lifecycle incentives
   - Microsoft: FastTrack, co-sell, ISV success, Azure credits
   - AWS: Partner programs, SDP, co-sell
4. **For each program found, capture:**
   - Program name and description
   - Eligibility requirements
   - Funding type (MDF, demo funds, co-sell credits, headcount subsidy)
   - Application process
   - Source URL
5. **Present findings** with confidence level:
   - HIGH: Official program page found with current details
   - MEDIUM: Referenced in partner materials but details may be outdated
   - LOW: Inferred from press releases or blog posts, needs verification with vendor rep

> **Note:** Vendor partner funding programs are often not fully documented publicly. Results should be treated as starting points for conversations with vendor partner managers, not definitive commitments.

### Step 8: ADVERSARIAL DEBATE (Optional)

If the user wants to iterate, run a full debate loop:

```bash
cd ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts && python3 forge.py debate --models <model_list> --document <file> --rounds 3
```

Each round:
1. Models critique the current GTM
2. Claude synthesizes critiques and proposes revisions
3. User approves/rejects each revision
4. Revised GTM goes back to models
5. Repeat until all models score 8+ on all dimensions, or max rounds reached

**Convergence criteria:**
- All dimensions average 8+ across all models = **CONVERGED**
- No critical issues (score < 5) remaining = **ACCEPTABLE**
- Max rounds reached with issues remaining = **NEEDS MANUAL REVIEW**

### Step 9: REFINEMENT & OUTPUT

1. Apply all approved changes to the GTM document
2. Add a confidence scorecard at the top:

```markdown
## GTM Forge Confidence Scorecard

| Dimension | Score | Status |
|-----------|-------|--------|
| Premise validity | 8.3 | STRONG |
| ICP clarity | 7.7 | GOOD |
| Competitive moat | 6.3 | NEEDS WORK |
| Commercial viability | 7.0 | GOOD |
| Technical accuracy | 9.0 | VERIFIED |
| Execution feasibility | 7.3 | GOOD |
| Pricing & packaging | 7.0 | GOOD |
| Market timing | 8.0 | STRONG |

**Overall: 7.6 / 10**
Vendor claims verified: 23/25 confirmed, 2 nuanced
Competitive counter-pitches: 3 generated
Funding programs identified: 4

Pipeline: research > verify > stress-test > debate (2 rounds) > refine
Models used: gpt-5.6-sol, gemini-3.1-pro, grok-4.7
```

3. Save the refined GTM alongside the original:
   - Report path: `{source_dir}/{source_name}-gtm-forge-{YYYY-MM-DD}.md`

4. Present final GTM to user

### Step 10: COST SUMMARY

Display total token usage and cost:
```
  GTM Forge Cost Summary
  ═══════════════════════
  Stage          | Tokens (in/out)  | Cost
  ───────────────────────────────────────
  Claim triage   | 12K / 4K         | $0.08
  Verification   | 8K / 3K          | $0.05
  Critique       | 15K / 8K         | $0.12
  Counter-pitch  | 10K / 6K         | $0.09
  Debate (2 rds) | 25K / 12K        | $0.18
  ───────────────────────────────────────
  Total          | 70K / 33K        | $0.52
```

## Key Principles

- **Evidence before assertions** -- every vendor claim must cite a source
- **Status quo is the real competitor** -- "doing nothing" beats most GTMs
- **User checkpoints** -- gates before money is spent or documents changed
- **MCP-first for Microsoft** -- prefer authoritative MCP sources over web search
- **Multi-model independence** -- never simulate diversity with subagents role-playing
- **Cost transparency** -- show token usage at every stage
- **Funding research is directional** -- partner programs change frequently, treat findings as conversation starters
- **No em dashes** -- use commas, periods, or "..." instead (author preference)

## CLI Reference

```bash
# Navigate to scripts directory first
cd ${CLAUDE_PLUGIN_ROOT}/skills/gtm-forge/scripts

# List available LLM providers
python3 forge.py providers

# Extract verifiable claims from GTM document
python3 forge.py extract <file>

# Multi-LLM triage of extracted claims
python3 forge.py triage claims.json --models <m1>,<m2> --document <file>

# Adversarial critique (scores 8 dimensions)
python3 forge.py critique --models <m1>,<m2> --document <file>

# Competitive counter-pitches
python3 forge.py counter-pitch --models <m1> --document <file> --competitors "Deloitte,Accenture"

# Funding program research
python3 forge.py research --query "Cisco partner funding AI security 2026"

# Full debate loop
python3 forge.py debate --models <m1>,<m2> --document <file> --rounds 3

# Manage profiles
python3 forge.py profiles list
python3 forge.py profiles create <name> --models <m1>,<m2>
python3 forge.py profiles use <name>
```

## GTM Document Structure

When building from scratch (Mode A), the generated GTM follows this structure:

```
# [Service Name] -- Go-To-Market Framework

## Executive Summary
- Visual tier overview (ASCII diagram)
- Funding model summary

## Premise
- Problem statement
- Why now
- Evidence of demand

## Positioning
- One-liner
- Core pitch
- Delivery model
- Commercial playbook

## Service Architecture
- Technology stack by layer
- What each layer does

## Service Tiers
### Tier 1: [Land]
### Tier 2: [Expand]
### Tier 3: [Retain]

## Target Clients
- Ideal Client Profile
- Trigger events
- Internal client identification

## Competitive Positioning
- Competitor table
- The moat

## Vendor Relationships
- Role and commercial model per vendor

## Funding Model
- Who funds what
- What each party gets

## Success Metrics
- Internal (practice)
- Client-facing (reports)

## Launch Plan
- Phase 1: Validate
- Phase 2: Productise
- Phase 3: Launch

## Open Questions

## Action Items
```

## Supported Providers

| Provider | Env var | Example models |
|----------|---------|----------------|
| OpenAI | `OPENAI_API_KEY` | `gpt-6-astra`, `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.5-pro` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-fable-5-1`, `claude-opus-5`, `claude-sonnet-5` |
| Google | `GEMINI_API_KEY` | `gemini/gemini-3.1-pro-preview`, `gemini/gemini-3.8-flash` |
| xAI | `XAI_API_KEY` | `xai/grok-4.7`, `xai/grok-4.6` |
| Azure AI | `AZURE_AI_API_KEY` | `foundry/claude-opus-5`, `foundry/grok-4.5` |
| Mistral | `MISTRAL_API_KEY` | `mistral/mistral-large` |
| Groq | `GROQ_API_KEY` | `groq/llama-3.3-70b-versatile` |
| Deepseek | `DEEPSEEK_API_KEY` | `deepseek/deepseek-v4-pro`, `deepseek/deepseek-flash` |
| OpenRouter | `OPENROUTER_API_KEY` | `openrouter/openai/gpt-5.5-pro` |
| ZAI (GLM) | `ZAI_API_KEY` | `zai/glm-5.2` |
| Moonshot | `MOONSHOT_API_KEY` | `moonshot/kimi-k3` |
| MiniMax | `MINIMAX_API_KEY` | `minimax/MiniMax-M3` |
| Codex CLI | (ChatGPT subscription) | `codex/gpt-6-astra`, `codex/gpt-5.6-sol`, `codex/gpt-5.5` |
| Antigravity CLI | (Google account) | `antigravity/gemini-3.1-pro-high`, `antigravity/claude-sonnet-4-6` |
| Gemini CLI | (retired 2026-06-18) | use `antigravity/` or `gemini/` instead |

Note: ChatGPT-account Codex serves only the ChatGPT lineup (gpt-6-astra on eligible plans,
gpt-5.6-sol/terra/luna, gpt-5.5 until it retires 2026-10-14). Other models (gpt-5.3-codex,
gpt-5.5-pro) need Codex API-key auth or the `OPENAI_API_KEY` route.

Run `python3 forge.py providers` to see which keys are configured.
