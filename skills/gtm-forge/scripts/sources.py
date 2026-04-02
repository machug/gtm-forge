"""Source registry and domain detection for GTM document verification."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

REGISTRY_PATH = Path.home() / ".claude" / "gtm-forge" / "source-registry.json"

# Source registry for GTM verification -- maps vendors to search tools and keywords
SOURCE_REGISTRY: dict[str, dict] = {
    "microsoft": {
        "mcp_tools": ["microsoft_docs_search", "microsoft_docs_fetch"],
        "keywords": [
            "microsoft", "azure", "purview", "defender", "entra", "copilot",
            "m365", "e5", "e3", "intune", "sentinel", "fabric", "power platform",
            "sharepoint", "teams", "graph api", "conditional access",
            "sensitivity label", "dlp", "information protection",
        ],
        "doc_base": "https://learn.microsoft.com",
        "web_search_prefix": "site:learn.microsoft.com OR site:microsoft.com",
        "partner_programs": [
            "Microsoft AI Cloud Partner Program",
            "Solution Assessment",
            "Solutions Partner for Security",
            "FastTrack Ready Partner",
        ],
    },
    "cisco": {
        "mcp_tools": [],  # No Cisco MCP available
        "keywords": [
            "cisco", "ai defense", "webex", "meraki", "umbrella", "duo",
            "secure access", "thousandeyes", "appd", "splunk", "talos",
            "xdr", "secure endpoint", "ise", "dna", "catalyst",
        ],
        "doc_base": "https://www.cisco.com",
        "web_search_prefix": "site:cisco.com OR site:blogs.cisco.com OR site:community.cisco.com",
        "partner_programs": [
            "Cisco Partner Plus",
            "Lifecycle Incentives",
            "Solution Support",
            "Deal Registration",
        ],
    },
    "cyera": {
        "mcp_tools": [],
        "keywords": [
            "cyera", "dspm", "omni dlp", "ai guardian", "data dna",
            "data security posture", "shadow ai", "data discovery",
        ],
        "doc_base": "https://www.cyera.io",
        "web_search_prefix": "site:cyera.io OR site:cyera.com",
        "partner_programs": [],
    },
    "cultureai": {
        "mcp_tools": [],
        "keywords": [
            "cultureai", "culture ai", "human risk", "human risk management",
            "security awareness", "security culture",
        ],
        "doc_base": "https://www.culture.ai",
        "web_search_prefix": "site:culture.ai",
        "partner_programs": [],
    },
    "servicenow": {
        "mcp_tools": [],
        "keywords": [
            "servicenow", "snow", "ai control tower", "cmdb", "itsm",
            "itom", "secops", "vrm", "virtual agent", "now platform",
        ],
        "doc_base": "https://www.servicenow.com",
        "web_search_prefix": "site:servicenow.com OR site:docs.servicenow.com",
        "partner_programs": [
            "ServiceNow Partner Program",
            "Technology Partner",
            "Service Partner",
        ],
    },
    "paloalto": {
        "mcp_tools": [],
        "keywords": [
            "palo alto", "prisma", "cortex", "xsiam", "xdr", "xsoar",
            "strata", "pan-os", "wildfire", "unit 42", "prisma cloud",
            "prisma access", "prisma sase",
        ],
        "doc_base": "https://www.paloaltonetworks.com",
        "web_search_prefix": "site:paloaltonetworks.com OR site:docs.paloaltonetworks.com",
        "partner_programs": [
            "Palo Alto Networks NextWave Partner Program",
            "Cortex MSSP Program",
        ],
    },
    "crowdstrike": {
        "mcp_tools": [],
        "keywords": [
            "crowdstrike", "falcon", "charlotte ai", "humio", "logscale",
            "endpoint detection", "edr", "threat intelligence",
        ],
        "doc_base": "https://www.crowdstrike.com",
        "web_search_prefix": "site:crowdstrike.com OR site:falcon.crowdstrike.com",
        "partner_programs": [
            "CrowdStrike Elevate Partner Program",
            "MSSP Partner Program",
        ],
    },
    "aws": {
        "mcp_tools": [],
        "keywords": [
            "aws", "amazon web services", "bedrock", "sagemaker", "guardduty",
            "security hub", "macie", "inspector", "detective",
        ],
        "doc_base": "https://docs.aws.amazon.com",
        "web_search_prefix": "site:aws.amazon.com OR site:docs.aws.amazon.com",
        "partner_programs": [
            "AWS Partner Network",
            "AWS ISV Accelerate",
            "Migration Acceleration Program",
            "AWS Competency Program",
        ],
    },
    "google_cloud": {
        "mcp_tools": [],
        "keywords": [
            "google cloud", "gcp", "chronicle", "mandiant", "vertex ai",
            "bigquery", "cloud armor", "security command center",
        ],
        "doc_base": "https://cloud.google.com",
        "web_search_prefix": "site:cloud.google.com OR site:cloud.google.com/docs",
        "partner_programs": [
            "Google Cloud Partner Advantage",
            "Specialization",
        ],
    },
    "general": {
        "mcp_tools": [],
        "keywords": [],
        "doc_base": "",
        "web_search_prefix": "",
        "partner_programs": [],
    },
}

# Competitor profiles for counter-pitch generation
COMPETITOR_PROFILES: dict[str, dict] = {
    "deloitte": {
        "full_name": "Deloitte",
        "role": "AI & Cyber Practice Lead",
        "strengths": [
            "Global scale and brand recognition",
            "Deep regulatory and compliance expertise",
            "Existing C-suite relationships",
            "Large bench of consultants",
            "Cross-industry benchmarking data",
        ],
    },
    "accenture": {
        "full_name": "Accenture",
        "role": "Managing Director, Security",
        "strengths": [
            "Massive delivery capacity",
            "Strong vendor alliances (all major vendors)",
            "Accenture Security embedded offerings",
            "Global SOC network",
            "Industry-specific accelerators",
        ],
    },
    "pwc": {
        "full_name": "PwC",
        "role": "Cybersecurity & Privacy Partner",
        "strengths": [
            "Audit and compliance heritage",
            "Board-level trust and relationships",
            "Risk quantification frameworks",
            "Cross-border regulatory expertise",
        ],
    },
    "kpmg": {
        "full_name": "KPMG",
        "role": "Cyber Security Practice Lead",
        "strengths": [
            "Strong GRC and audit integration",
            "Industry regulatory expertise",
            "Board reporting frameworks",
        ],
    },
    "wiz": {
        "full_name": "Wiz",
        "role": "Head of Channel & Alliances",
        "strengths": [
            "Cloud-native security platform",
            "Agentless architecture",
            "Rapid deployment (minutes not months)",
            "Strong product-led growth",
        ],
    },
    "arctic_wolf": {
        "full_name": "Arctic Wolf",
        "role": "VP of Managed Services",
        "strengths": [
            "Purpose-built for managed security",
            "Concierge security model",
            "24x7 SOC operations",
            "Simple per-user pricing",
        ],
    },
}


def detect_document_domains(content: str) -> list[str]:
    """Detect which vendor/technology domains are referenced in a document.

    Args:
        content: The document text to analyze.

    Returns:
        List of domain keys from SOURCE_REGISTRY that were detected.
    """
    content_lower = content.lower()
    detected = []

    for domain, config in SOURCE_REGISTRY.items():
        if domain == "general":
            continue
        keywords = config.get("keywords", [])
        if any(kw in content_lower for kw in keywords):
            detected.append(domain)

    if not detected:
        detected.append("general")

    return detected


def find_relevant_sources(claim: str, registry: Optional[dict] = None) -> list[dict]:
    """Find relevant sources for verifying a specific claim.

    Args:
        claim: The claim text to find sources for.
        registry: Optional custom registry. Uses SOURCE_REGISTRY if not provided.

    Returns:
        List of dicts with {domain, mcp_tools, web_search_prefix, doc_base}.
    """
    if registry is None:
        registry = SOURCE_REGISTRY

    claim_lower = claim.lower()
    sources = []

    for domain, config in registry.items():
        if domain == "general":
            continue
        keywords = config.get("keywords", [])
        if any(kw in claim_lower for kw in keywords):
            sources.append({
                "domain": domain,
                "mcp_tools": config.get("mcp_tools", []),
                "web_search_prefix": config.get("web_search_prefix", ""),
                "doc_base": config.get("doc_base", ""),
            })

    # Always include general as fallback
    if not sources:
        sources.append({
            "domain": "general",
            "mcp_tools": [],
            "web_search_prefix": "",
            "doc_base": "",
        })

    return sources


def get_available_mcps() -> list[str]:
    """Detect which MCP servers are available in the current environment.

    Checks for known MCP tool patterns in the environment. This is a best-effort
    detection -- the actual availability depends on the Claude Code session.

    Returns:
        List of MCP tool name prefixes that appear to be available.
    """
    # Known MCP tool prefixes we look for
    known_mcps = [
        "mcp__microsoft_docs_mcp__",
        "mcp__claude_ai_Microsoft_Docs__",
        "mcp__plugin_context7_context7__",
    ]
    # In practice, MCP availability is determined at runtime by the skill orchestrator.
    # This function provides the static list of MCPs we know how to use.
    return known_mcps


def get_competitor_profile(name: str) -> Optional[dict]:
    """Look up a competitor profile by name (case-insensitive, partial match).

    Args:
        name: Competitor name to look up.

    Returns:
        Competitor profile dict, or None if not found.
    """
    name_lower = name.lower().strip().replace(" ", "_")

    # Exact match
    if name_lower in COMPETITOR_PROFILES:
        return COMPETITOR_PROFILES[name_lower]

    # Partial match
    for key, profile in COMPETITOR_PROFILES.items():
        if name_lower in key or name_lower in profile["full_name"].lower():
            return profile

    # Not found -- return a generic profile
    return {
        "full_name": name.strip(),
        "role": "Practice Lead",
        "strengths": ["(Custom competitor -- strengths not pre-configured)"],
    }


def build_source_plan(domains: list[str]) -> list[dict]:
    """Build a verification source plan for detected domains.

    Args:
        domains: List of domain keys from detect_document_domains().

    Returns:
        List of source plan entries with domain, tools, and search guidance.
    """
    plan = []
    for domain in domains:
        config = SOURCE_REGISTRY.get(domain, SOURCE_REGISTRY["general"])
        entry = {
            "domain": domain,
            "mcp_tools": config.get("mcp_tools", []),
            "web_search_prefix": config.get("web_search_prefix", ""),
            "doc_base": config.get("doc_base", ""),
            "partner_programs": config.get("partner_programs", []),
        }
        plan.append(entry)
    return plan


def load_custom_registry() -> dict:
    """Load custom source registry additions from disk."""
    if not REGISTRY_PATH.exists():
        return {}
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except json.JSONDecodeError as e:
        print(f"Warning: Invalid JSON in source registry: {e}", file=sys.stderr)
        return {}


def save_custom_registry(additions: dict):
    """Save custom registry additions to disk."""
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    REGISTRY_PATH.write_text(json.dumps(additions, indent=2))
    REGISTRY_PATH.chmod(0o600)


def get_merged_registry() -> dict:
    """Get the full registry: defaults merged with custom additions."""
    merged = dict(SOURCE_REGISTRY)
    custom = load_custom_registry()
    merged.update(custom)
    return merged


def list_sources():
    """Print the source registry in a readable format."""
    registry = get_merged_registry()
    print("GTM Source Registry:\n")

    for domain, config in sorted(registry.items()):
        if domain == "general":
            continue
        mcp_status = "MCP available" if config.get("mcp_tools") else "Web search only"
        keywords = config.get("keywords", [])[:5]
        programs = config.get("partner_programs", [])

        print(f"  {domain}")
        print(f"    Status:   {mcp_status}")
        print(f"    Keywords: {', '.join(keywords)}")
        if config.get("doc_base"):
            print(f"    Docs:     {config['doc_base']}")
        if programs:
            print(f"    Programs: {', '.join(programs)}")
        print()

    print("Competitors:\n")
    for key, profile in sorted(COMPETITOR_PROFILES.items()):
        print(f"  {profile['full_name']}")
        print(f"    Role:      {profile['role']}")
        print(f"    Strengths: {', '.join(profile['strengths'][:3])}")
        print()
