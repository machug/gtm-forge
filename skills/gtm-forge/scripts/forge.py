#!/usr/bin/env python3
"""
GTM Forge: multi-LLM adversarial Go-To-Market strategy development.

Stress-tests enterprise managed services GTM strategies using multiple LLMs
for critique, counter-pitch, funding research, and iterative debate.

Usage:
    python3 forge.py providers
    python3 forge.py profiles list
    python3 forge.py profiles save <name> --models m1,m2
    python3 forge.py sources
    python3 forge.py extract <file>
    python3 forge.py triage <claims.json> --models m1,m2 --document <file>
    python3 forge.py critique --models gpt-5.6-sol,gemini/gemini-3.1-pro-preview --document <file>
    python3 forge.py counter-pitch --models gpt-5.6-sol --document <file> --competitors "Deloitte,Accenture"
    python3 forge.py research --models gpt-5.6-sol,xai/grok-4.5 --query "Cisco partner funding AI security 2026"
    python3 forge.py debate --models gpt-5.6-sol,antigravity/gemini-3.1-pro-high --document <file> --rounds 3

Exit codes:
    0 - Success
    1 - API error or runtime failure
    2 - Missing API key or config error
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add scripts dir to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from models import (
    CostTracker,
    CritiqueResponse,
    GenericResponse,
    cost_tracker,
    critique_parallel,
    generic_parallel,
    parse_critique_json,
)
from prompts import (
    COUNTER_PITCH_SYSTEM,
    COUNTER_PITCH_USER,
    CRITIQUE_REPORT_TEMPLATE,
    CRITIQUE_SYSTEM,
    CRITIQUE_USER,
    DEBATE_CRITIQUE_USER,
    DEBATE_REPORT_TEMPLATE,
    EXTRACT_CLAIMS_SYSTEM,
    EXTRACT_CLAIMS_USER,
    FUNDING_RESEARCH_SYSTEM,
    FUNDING_RESEARCH_USER,
    SYNTHESIS_SYSTEM,
    SYNTHESIS_USER,
    TRIAGE_SYSTEM,
    TRIAGE_USER,
    VERIFY_SYSTEM,
    VERIFY_USER,
)
from providers import (
    get_available_providers,
    list_profiles,
    list_providers,
    load_profile,
    save_profile,
    validate_model_credentials,
    warn_codex_chatgpt_model_support,
    warn_openai_base_url_override,
)
from sources import (
    COMPETITOR_PROFILES,
    build_source_plan,
    detect_document_domains,
    get_competitor_profile,
    list_sources,
)


def validate_models_or_exit(models: list[str]) -> list[str]:
    """Validate credentials for requested models; exit(2) if any are missing.

    Also emits preflight warnings for Codex ChatGPT-account model mismatches
    and a globally rerouted OPENAI_BASE_URL.
    """
    valid, invalid = validate_model_credentials(models)
    if invalid:
        print(f"Error: Missing credentials for: {', '.join(invalid)}", file=sys.stderr)
        print("Run: python3 forge.py providers", file=sys.stderr)
        sys.exit(2)
    warn_codex_chatgpt_model_support(valid)
    warn_openai_base_url_override(valid)
    return valid


# --- Parsing helpers ---

def parse_claims_output(text: str) -> list[dict]:
    """Parse [CLAIM] blocks from extraction output."""
    claims = []
    blocks = re.findall(r"\[CLAIM\](.*?)\[/CLAIM\]", text, re.DOTALL)

    for block in blocks:
        claim: dict[str, str] = {}
        for line in block.strip().split("\n"):
            line = line.strip()
            if line.startswith("id:"):
                claim["id"] = line[3:].strip()
            elif line.startswith("text:"):
                claim["text"] = line[5:].strip()
            elif line.startswith("category:"):
                claim["category"] = line[9:].strip()
            elif line.startswith("section:"):
                claim["section"] = line[8:].strip()

        if claim.get("id") and claim.get("text"):
            claims.append(claim)

    return claims


def parse_triage_response(response_text: str) -> dict[str, dict]:
    """Parse [TRIAGE] blocks from model response.

    Returns {claim_id: {"verdict": ..., "reason": ...}}
    """
    verdicts = {}
    blocks = re.findall(r"\[TRIAGE\](.*?)\[/TRIAGE\]", response_text, re.DOTALL)

    for block in blocks:
        claim_id = None
        verdict = None
        reason = ""

        for line in block.strip().split("\n"):
            line = line.strip()
            if line.startswith("id:"):
                claim_id = line[3:].strip()
            elif line.startswith("verdict:"):
                verdict = line[8:].strip().upper()
            elif line.startswith("reason:"):
                reason = line[7:].strip()

        if claim_id and verdict:
            verdicts[claim_id] = {"verdict": verdict, "reason": reason}

    return verdicts


def extract_revised_gtm(response_text: str) -> Optional[str]:
    """Extract revised GTM content from [GTM]...[/GTM] tags."""
    if "[GTM]" not in response_text or "[/GTM]" not in response_text:
        return None
    start = response_text.find("[GTM]") + len("[GTM]")
    end = response_text.find("[/GTM]")
    return response_text[start:end].strip()


# --- Score aggregation ---

DIMENSIONS = [
    "premise_validity", "icp_clarity", "competitive_differentiation",
    "commercial_viability", "technical_accuracy", "execution_feasibility",
    "pricing_packaging", "market_timing",
]


def aggregate_scores(responses: list[CritiqueResponse]) -> dict[str, float]:
    """Average scores across all responding models."""
    totals: dict[str, list[int]] = {d: [] for d in DIMENSIONS}
    for r in responses:
        if r.error:
            continue
        for dim in DIMENSIONS:
            if dim in r.scores:
                totals[dim].append(r.scores[dim])
    return {
        dim: round(sum(vals) / len(vals), 1) if vals else 0.0
        for dim, vals in totals.items()
    }


def aggregate_issues(responses: list[CritiqueResponse]) -> list[dict]:
    """Collect and deduplicate issues across models."""
    all_issues = []
    for r in responses:
        if r.error:
            continue
        for issue in r.issues:
            issue_copy = dict(issue)
            issue_copy["source_model"] = r.model
            all_issues.append(issue_copy)
    return all_issues


def scores_converged(avg_scores: dict[str, float], threshold: int = 8) -> bool:
    """Check if all dimension scores meet the convergence threshold."""
    if not avg_scores:
        return False
    return all(v >= threshold for v in avg_scores.values())


# --- Report generation ---

def generate_critique_report(
    source_path: str,
    models: list[str],
    responses: list[CritiqueResponse],
    tracker: CostTracker,
) -> str:
    """Generate a formatted critique report."""
    avg_scores = aggregate_scores(responses)
    all_issues = aggregate_issues(responses)

    # Score table
    model_names = [r.model.split("/")[-1] if "/" in r.model else r.model for r in responses if not r.error]
    score_headers = " | ".join(model_names)
    score_separators = " | ".join(["---"] * len(model_names))

    score_rows_lines = []
    for dim in DIMENSIONS:
        dim_label = dim.replace("_", " ").title()
        model_scores = []
        for r in responses:
            if r.error:
                continue
            model_scores.append(str(r.scores.get(dim, "-")))
        avg = avg_scores.get(dim, 0)
        score_rows_lines.append(f"| {dim_label} | {' | '.join(model_scores)} | {avg} |")
    score_rows = "\n".join(score_rows_lines)

    # Overall assessments
    assessment_parts = []
    for r in responses:
        if r.error:
            assessment_parts.append(f"**{r.model}**: ERROR -- {r.error}")
            continue
        # Try to extract overall_assessment from JSON
        try:
            text = r.response.strip()
            if "```json" in text:
                s = text.find("```json") + 7
                e = text.find("```", s)
                text = text[s:e].strip()
            brace_s = text.find("{")
            brace_e = text.rfind("}")
            if brace_s >= 0 and brace_e > brace_s:
                data = json.loads(text[brace_s:brace_e + 1])
                assessment = data.get("overall_assessment", "(No assessment provided)")
            else:
                assessment = "(Could not parse assessment)"
        except Exception:
            assessment = "(Could not parse assessment)"
        assessment_parts.append(f"**{r.model}**: {assessment}")
    overall_assessments = "\n\n".join(assessment_parts)

    # Issues by severity
    critical = [i for i in all_issues if i.get("severity") == "critical"]
    major = [i for i in all_issues if i.get("severity") == "major"]
    minor = [i for i in all_issues if i.get("severity") == "minor"]

    def format_issues(issues: list[dict]) -> str:
        if not issues:
            return "None found."
        lines = []
        for i in issues:
            lines.append(f"- **[{i.get('dimension', 'N/A')}]** {i.get('issue', 'N/A')}")
            lines.append(f"  - Suggestion: {i.get('suggestion', 'N/A')}")
            lines.append(f"  - Source: {i.get('source_model', 'N/A')}")
        return "\n".join(lines)

    report = CRITIQUE_REPORT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        source_path=source_path,
        models=", ".join(models),
        score_headers=score_headers,
        score_separators=score_separators,
        score_rows=score_rows,
        overall_assessments=overall_assessments,
        critical_issues=format_issues(critical),
        major_issues=format_issues(major),
        minor_issues=format_issues(minor),
        cost_summary=tracker.summary(),
    )
    return report


# --- CLI Commands ---

def cmd_providers(args):
    """List available LLM providers."""
    list_providers()


def cmd_profiles(args):
    """List or manage profiles."""
    if args.subcommand == "list":
        list_profiles()
    elif args.subcommand == "save":
        if not args.name or not args.models:
            print("Error: --name and --models required for save", file=sys.stderr)
            sys.exit(2)
        config = {"models": args.models}
        if args.competitors:
            config["competitors"] = args.competitors
        save_profile(args.name, config)


def cmd_sources(args):
    """List source registry and competitor profiles."""
    list_sources()


def cmd_extract(args):
    """Extract verifiable claims from a GTM document."""
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    content = file_path.read_text()
    domains = detect_document_domains(content)

    print(f"Document: {file_path}", file=sys.stderr)
    print(f"Length: {len(content):,} characters", file=sys.stderr)
    print(f"Detected vendors: {', '.join(domains)}", file=sys.stderr)
    print(file=sys.stderr)

    # Output the extraction prompt for the orchestrating agent
    prompt = EXTRACT_CLAIMS_USER.format(document=content)
    print("=== EXTRACTION PROMPT ===", file=sys.stderr)
    print(f"System prompt ({len(EXTRACT_CLAIMS_SYSTEM)} chars)", file=sys.stderr)
    print(f"User prompt ({len(prompt)} chars)", file=sys.stderr)
    print(file=sys.stderr)
    print("--- System Prompt ---", file=sys.stderr)
    print(EXTRACT_CLAIMS_SYSTEM, file=sys.stderr)
    print(file=sys.stderr)
    print("Send this to Claude to extract claims. Output will contain [CLAIM]...[/CLAIM] blocks.", file=sys.stderr)

    # Build source plan
    plan = build_source_plan(domains)
    print(f"\n--- Source Plan for Verification ---", file=sys.stderr)
    for entry in plan:
        mcp_note = f"MCP: {', '.join(entry['mcp_tools'])}" if entry["mcp_tools"] else "Web search only"
        print(f"  {entry['domain']}: {mcp_note}", file=sys.stderr)


def cmd_triage(args):
    """Run triage on extracted claims using multiple models."""
    valid = validate_models_or_exit(args.models.split(","))

    # Read claims
    claims_path = Path(args.claims)
    if not claims_path.exists():
        print(f"Error: Claims file not found: {claims_path}", file=sys.stderr)
        sys.exit(1)

    claims = json.loads(claims_path.read_text())
    document = Path(args.document).read_text() if args.document else ""

    # Format claims for prompt
    claims_text = "\n".join(
        f"[{c['id']}] ({c.get('category', 'N/A')}) {c['text']}"
        for c in claims
    )
    user_message = TRIAGE_USER.format(claims=claims_text, document=document)

    print(f"Triaging {len(claims)} claims with {len(valid)} models: {', '.join(valid)}", file=sys.stderr)

    # Use generic_parallel since triage returns text with [TRIAGE] blocks
    responses = generic_parallel(valid, TRIAGE_SYSTEM, user_message)

    # Parse and display triage results
    flagged = []
    verified = []

    for resp in responses:
        if resp.error:
            print(f"\n{resp.model}: ERROR -- {resp.error}", file=sys.stderr)
            continue

        verdicts = parse_triage_response(resp.response)
        print(f"\n{resp.model}: {len(verdicts)} verdicts", file=sys.stderr)
        for cid, v in sorted(verdicts.items()):
            icon = {"CONFIDENT": "OK", "UNCERTAIN": "??", "SUSPECT": "!!"}.get(v["verdict"], "??")
            print(f"  {icon} [{cid}] {v['verdict']}: {v['reason']}", file=sys.stderr)

    print(cost_tracker.summary(), file=sys.stderr)

    # Output flagged claims as JSON to stdout
    output = {"claims": claims, "triage_results": []}
    for resp in responses:
        if not resp.error:
            output["triage_results"].append({
                "model": resp.model,
                "verdicts": parse_triage_response(resp.response),
            })
    print(json.dumps(output, indent=2))


def cmd_critique(args):
    """Run adversarial critique on a GTM document."""
    valid = validate_models_or_exit(args.models.split(","))

    file_path = Path(args.document)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    content = file_path.read_text()
    domains = detect_document_domains(content)
    user_message = CRITIQUE_USER.format(document=content)

    print(f"Document: {file_path}", file=sys.stderr)
    print(f"Detected vendors: {', '.join(domains)}", file=sys.stderr)
    print(f"Critiquing with {len(valid)} models: {', '.join(valid)}", file=sys.stderr)
    print(file=sys.stderr)

    responses = critique_parallel(valid, CRITIQUE_SYSTEM, user_message)

    # Display scores
    for r in responses:
        if r.error:
            print(f"\n{r.model}: ERROR -- {r.error}", file=sys.stderr)
            continue
        print(f"\n{r.model}:", file=sys.stderr)
        for dim in DIMENSIONS:
            score = r.scores.get(dim, "-")
            print(f"  {dim.replace('_', ' ').title():35} {score}/10", file=sys.stderr)
        print(f"  Issues found: {len(r.issues)}", file=sys.stderr)

    avg = aggregate_scores(responses)
    print(f"\n--- Average Scores ---", file=sys.stderr)
    for dim in DIMENSIONS:
        print(f"  {dim.replace('_', ' ').title():35} {avg.get(dim, 0)}/10", file=sys.stderr)

    print(cost_tracker.summary(), file=sys.stderr)

    # Generate report to stdout
    report = generate_critique_report(str(file_path), valid, responses, cost_tracker)
    print(report)


def cmd_counter_pitch(args):
    """Generate competitor counter-pitches."""
    valid = validate_models_or_exit(args.models.split(","))

    file_path = Path(args.document)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    content = file_path.read_text()
    competitors = [c.strip() for c in args.competitors.split(",")]

    print(f"Document: {file_path}", file=sys.stderr)
    print(f"Competitors: {', '.join(competitors)}", file=sys.stderr)
    print(f"Models: {', '.join(valid)}", file=sys.stderr)
    print(file=sys.stderr)

    all_pitches = []
    for competitor_name in competitors:
        profile = get_competitor_profile(competitor_name)
        system_prompt = COUNTER_PITCH_SYSTEM.format(
            competitor_role=profile["role"],
            competitor_name=profile["full_name"],
        )
        user_message = COUNTER_PITCH_USER.format(document=content)

        print(f"Generating counter-pitch as {profile['full_name']}...", file=sys.stderr)
        responses = generic_parallel(valid, system_prompt, user_message)

        for resp in responses:
            if resp.error:
                print(f"  {resp.model}: ERROR -- {resp.error}", file=sys.stderr)
            else:
                all_pitches.append({
                    "competitor": profile["full_name"],
                    "model": resp.model,
                    "pitch": resp.response,
                })
                print(f"  {resp.model}: Done ({resp.output_tokens:,} tokens)", file=sys.stderr)

    print(cost_tracker.summary(), file=sys.stderr)

    # Output to stdout
    print(f"\n# Counter-Pitch Report\n")
    print(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"**Source:** {file_path}")
    print(f"**Competitors:** {', '.join(competitors)}")
    print(f"**Models:** {', '.join(valid)}\n")

    for pitch in all_pitches:
        print(f"---\n## {pitch['competitor']} (via {pitch['model']})\n")
        print(pitch["pitch"])
        print()


def cmd_research(args):
    """Research vendor funding programs and partner incentives."""
    valid = validate_models_or_exit(args.models.split(","))

    context = ""
    if args.document:
        doc_path = Path(args.document)
        if doc_path.exists():
            context = doc_path.read_text()

    user_message = FUNDING_RESEARCH_USER.format(query=args.query, context=context)

    print(f"Researching: {args.query}", file=sys.stderr)
    print(f"Models: {', '.join(valid)}", file=sys.stderr)
    print(file=sys.stderr)

    responses = generic_parallel(valid, FUNDING_RESEARCH_SYSTEM, user_message)

    for resp in responses:
        if resp.error:
            print(f"{resp.model}: ERROR -- {resp.error}", file=sys.stderr)
        else:
            print(f"--- {resp.model} ---\n")
            print(resp.response)
            print()

    print(cost_tracker.summary(), file=sys.stderr)


def cmd_debate(args):
    """Run multi-round adversarial debate on a GTM document."""
    valid = validate_models_or_exit(args.models.split(","))

    file_path = Path(args.document)
    if not file_path.exists():
        print(f"Error: File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    max_rounds = args.rounds
    threshold = args.threshold
    current_gtm = file_path.read_text()
    domains = detect_document_domains(current_gtm)

    print(f"Document: {file_path}", file=sys.stderr)
    print(f"Detected vendors: {', '.join(domains)}", file=sys.stderr)
    print(f"Models: {', '.join(valid)}", file=sys.stderr)
    print(f"Max rounds: {max_rounds}, convergence threshold: {threshold}", file=sys.stderr)
    print(file=sys.stderr)

    score_history = []
    converged = False

    for round_num in range(1, max_rounds + 1):
        print(f"=== Round {round_num}/{max_rounds} ===", file=sys.stderr)

        # Build previous context for round > 1
        previous_context = ""
        if round_num > 1 and score_history:
            prev = score_history[-1]
            prev_lines = [f"Previous round scores:"]
            for dim in DIMENSIONS:
                prev_lines.append(f"  {dim}: {prev.get(dim, 'N/A')}")
            previous_context = "\n".join(prev_lines)

        user_message = DEBATE_CRITIQUE_USER.format(
            round=round_num,
            previous_context=previous_context,
            document=current_gtm,
        )

        # Critique phase
        responses = critique_parallel(valid, CRITIQUE_SYSTEM, user_message)

        avg_scores = aggregate_scores(responses)
        score_history.append(avg_scores)
        all_issues = aggregate_issues(responses)

        # Display round results
        print(f"\nRound {round_num} scores:", file=sys.stderr)
        for dim in DIMENSIONS:
            print(f"  {dim.replace('_', ' ').title():35} {avg_scores.get(dim, 0)}/10", file=sys.stderr)
        print(f"  Issues: {len(all_issues)}", file=sys.stderr)

        # Check convergence
        if scores_converged(avg_scores, threshold):
            print(f"\nConverged! All scores >= {threshold}.", file=sys.stderr)
            converged = True
            break

        if round_num < max_rounds:
            # Synthesis phase -- use first model to synthesize
            print(f"\nSynthesizing feedback...", file=sys.stderr)
            critiques_text = ""
            for r in responses:
                if not r.error:
                    critiques_text += f"\n### {r.model}\n{r.response}\n"

            synth_message = SYNTHESIS_USER.format(
                document=current_gtm,
                critiques=critiques_text,
            )
            synth_responses = generic_parallel(
                [valid[0]], SYNTHESIS_SYSTEM, synth_message, max_tokens=16000,
            )

            for sr in synth_responses:
                if sr.error:
                    print(f"  Synthesis error: {sr.error}", file=sys.stderr)
                    continue
                revised = extract_revised_gtm(sr.response)
                if revised:
                    current_gtm = revised
                    print(f"  GTM revised ({len(revised):,} chars)", file=sys.stderr)
                else:
                    print(f"  Warning: No [GTM] tags in synthesis output", file=sys.stderr)

    # Final output
    print(cost_tracker.summary(), file=sys.stderr)

    # Build score progression table
    progression_lines = ["| Round | " + " | ".join(d.replace("_", " ").title() for d in DIMENSIONS) + " |"]
    progression_lines.append("|-------|" + "|".join(["---"] * len(DIMENSIONS)) + "|")
    for i, scores in enumerate(score_history, 1):
        row = f"| {i} | " + " | ".join(str(scores.get(d, "-")) for d in DIMENSIONS) + " |"
        progression_lines.append(row)
    score_progression = "\n".join(progression_lines)

    # Final scores
    final = score_history[-1] if score_history else {}
    final_lines = []
    for dim in DIMENSIONS:
        final_lines.append(f"- **{dim.replace('_', ' ').title()}**: {final.get(dim, 'N/A')}/10")
    final_scores = "\n".join(final_lines)

    report = DEBATE_REPORT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d %H:%M"),
        source_path=str(file_path),
        models=", ".join(valid),
        rounds=len(score_history),
        converged="Yes" if converged else f"No (max rounds reached)",
        score_progression=score_progression,
        final_scores=final_scores,
        revised_gtm=current_gtm,
        cost_summary=cost_tracker.summary(),
    )
    print(report)


# --- Main ---

def main():
    parser = argparse.ArgumentParser(
        description="GTM Forge: stress-test Go-To-Market strategies with multi-LLM adversarial analysis"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # providers
    p_providers = subparsers.add_parser("providers", help="List available LLM providers")
    p_providers.set_defaults(func=cmd_providers)

    # profiles
    p_profiles = subparsers.add_parser("profiles", help="Manage saved profiles")
    p_profiles.add_argument("subcommand", choices=["list", "save"])
    p_profiles.add_argument("--name", help="Profile name")
    p_profiles.add_argument("--models", help="Comma-separated model list")
    p_profiles.add_argument("--competitors", help="Default competitors for this profile")
    p_profiles.set_defaults(func=cmd_profiles)

    # sources
    p_sources = subparsers.add_parser("sources", help="List vendor source registry")
    p_sources.set_defaults(func=cmd_sources)

    # extract
    p_extract = subparsers.add_parser("extract", help="Extract verifiable claims from GTM doc")
    p_extract.add_argument("file", help="GTM document to extract claims from")
    p_extract.set_defaults(func=cmd_extract)

    # triage
    p_triage = subparsers.add_parser("triage", help="Triage extracted claims with multiple models")
    p_triage.add_argument("claims", help="JSON file of extracted claims")
    p_triage.add_argument("--models", required=True, help="Comma-separated model list")
    p_triage.add_argument("--document", help="Original GTM document for context")
    p_triage.set_defaults(func=cmd_triage)

    # critique
    p_critique = subparsers.add_parser("critique", help="Adversarial GTM critique")
    p_critique.add_argument("--models", required=True, help="Comma-separated model list")
    p_critique.add_argument("--document", required=True, help="GTM document to critique")
    p_critique.set_defaults(func=cmd_critique)

    # counter-pitch
    p_counter = subparsers.add_parser("counter-pitch", help="Generate competitor counter-pitches")
    p_counter.add_argument("--models", required=True, help="Comma-separated model list")
    p_counter.add_argument("--document", required=True, help="GTM document")
    p_counter.add_argument("--competitors", required=True, help="Comma-separated competitor names")
    p_counter.set_defaults(func=cmd_counter_pitch)

    # research
    p_research = subparsers.add_parser("research", help="Research vendor funding programs")
    p_research.add_argument("--models", required=True, help="Comma-separated model list")
    p_research.add_argument("--query", required=True, help="Research query")
    p_research.add_argument("--document", help="Optional GTM document for context")
    p_research.set_defaults(func=cmd_research)

    # debate
    p_debate = subparsers.add_parser("debate", help="Multi-round adversarial debate")
    p_debate.add_argument("--models", required=True, help="Comma-separated model list")
    p_debate.add_argument("--document", required=True, help="GTM document")
    p_debate.add_argument("--rounds", type=int, default=3, help="Maximum debate rounds (default: 3)")
    p_debate.add_argument("--threshold", type=int, default=8, help="Convergence threshold (default: 8)")
    p_debate.set_defaults(func=cmd_debate)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
