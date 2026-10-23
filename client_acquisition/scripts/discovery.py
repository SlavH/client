"""Lead discovery, scoring, and proposal generation logic.

Pure-Python helpers (no external network). The actual business discovery step
uses OpenCode web search/browser tools and feeds verified leads into this module.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from client_acquisition.scripts.crm import (
    CRM,
    make_lead_key,
    normalize_domain,
    utc_now,
)

MAX_SCORE = 100
DEFAULT_THRESHOLD = 60


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: str) -> str:
    joined = "|".join(p or "" for p in parts)
    return "id_" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def select_language(business_name: str, country: str, city: str,
                    observed_lang_hints: Optional[List[str]] = None) -> str:
    """Choose the most appropriate proposal language: Armenian, Russian, English.

    Default: English for broader reach; Armenian for local Yerevan businesses;
    Russian when Russian-language cues are observed.
    """
    country_l = (country or "").lower()
    city_l = (city or "").lower()
    name_l = (business_name or "").lower()
    hints = " ".join(observed_lang_hints or []).lower()

    if country_l == "armenia" or city_l == "yerevan":
        if "ru" in hints or "russian" in hints:
            return "Russian"
        return "Armenian"
    if "russian" in hints:
        return "Russian"
    return "English"


# --------------------------------------------------------------------------- scoring
def score_lead(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Score a lead 0-100 with explicit per-component explanations.

    Components:
      - website_or_automation_opportunity (0-35)
      - service_fit (0-25)
      - evidence_reliability (0-20)
      - target_market_relevance (0-10)
      - contact_route (0-10)

    Missing evidence lowers confidence; it is never treated as proof of a problem.
    """
    components: Dict[str, Dict[str, Any]] = {}

    # 1. Website / automation opportunity (0-35)
    has_website = bool(evidence.get("website_url"))
    website_quality = evidence.get("website_quality", "unknown")  # good|outdated|missing|unknown
    opp_mentioned = bool(evidence.get("proposed_opportunity"))

    if not has_website:
        w_score = 30
        w_expl = "No public website found: a clear website opportunity exists (30/35). No observable evidence of existing site quality, so capped below max."
    elif website_quality == "outdated":
        w_score = 35
        w_expl = "Website exists but observable evidence indicates outdated/poor usability (35/35)."
    elif website_quality == "good":
        w_score = 10
        w_expl = "Website appears well-maintained; limited automation opportunity remains (10/35)."
    elif website_quality == "missing":
        w_score = 32
        w_expl = "Website referenced but not accessible/verifiable; missing or unreliable presence (32/35)."
    else:
        w_score = 15
        w_expl = "Website status unknown; cannot confirm an opportunity from evidence alone (15/35)."

    if opp_mentioned:
        w_score = min(35, w_score + 5)
        w_expl += " A specific improvement opportunity was identified (+5)."

    components["website_or_automation_opportunity"] = {
        "score": min(35, w_score),
        "max": 35,
        "explanation": w_expl,
    }

    # 2. Service fit (0-25)
    category = (evidence.get("business_category") or "").lower()
    opp = (evidence.get("proposed_opportunity") or "").lower()
    fit_keywords = ("web", "website", "app", "software", "automation", "ai",
                    "booking", "inquiry", "lead", "digital", "online", "e-commerce")
    fit_hits = sum(1 for k in fit_keywords if k in category or k in opp)
    if fit_hits >= 2:
        s_score = 25
        s_expl = "Strong fit with Full-Stack web application / AI automation services (25/25)."
    elif fit_hits == 1:
        s_score = 15
        s_expl = "Moderate fit; one relevant signal detected (15/25)."
    else:
        s_score = 5
        s_expl = "No clear fit signal from category or proposed opportunity (5/25)."

    components["service_fit"] = {
        "score": s_score,
        "max": 25,
        "explanation": s_expl,
    }

    # 3. Evidence reliability (0-20)
    sources = evidence.get("public_source_urls") or []
    num_sources = len([s for s in sources if s])
    has_official = bool(evidence.get("website_url"))
    if num_sources >= 3 and has_official:
        e_score = 20
        e_expl = "Multiple reliable public sources plus official website (20/20)."
    elif num_sources >= 2 or has_official:
        e_score = 13
        e_expl = "Some reliable public evidence; limited source count (13/20)."
    elif num_sources == 1:
        e_score = 7
        e_expl = "Single source only; low reliability (7/20)."
    else:
        e_score = 0
        e_expl = "No verifiable public sources; evidence unreliable (0/20)."

    components["evidence_reliability"] = {
        "score": e_score,
        "max": 20,
        "explanation": e_expl,
    }

    # 4. Target market relevance (0-10)
    country = (evidence.get("country") or "").lower()
    city = (evidence.get("city") or "").lower()
    priority_city = (evidence.get("priority_city") or "yerevan").lower()
    if country == "armenia" and city == priority_city:
        t_score = 10
        t_expl = "In priority city (Yerevan, Armenia) (10/10)."
    elif country == "armenia":
        t_score = 7
        t_expl = "In Armenia but outside priority city (7/10)."
    else:
        t_score = 2
        t_expl = "Outside target market (2/10)."

    components["target_market_relevance"] = {
        "score": t_score,
        "max": 10,
        "explanation": t_expl,
    }

    # 5. Public contact route (0-10)
    contact_page = bool(evidence.get("public_contact_page"))
    contact_any = contact_page or bool(evidence.get("public_source_urls"))
    if contact_page:
        c_score = 10
        c_expl = "Official public business contact page available (10/10)."
    elif contact_any:
        c_score = 6
        c_expl = "Public source URLs available; no dedicated contact page confirmed (6/10)."
    else:
        c_score = 0
        c_expl = "No public contact route identified (0/10)."

    components["contact_route"] = {
        "score": c_score,
        "max": 10,
        "explanation": c_expl,
    }

    total = sum(c["score"] for c in components.values())
    return {
        "total_score": min(MAX_SCORE, total),
        "max_score": MAX_SCORE,
        "components": components,
    }


# --------------------------------------------------------------------------- proposal generation
def generate_proposal(lead: Dict[str, Any], language: str = "English") -> Dict[str, Any]:
    """Generate a personalized proposal draft from a verified lead.

    Never invents contact info. Never pretends a demo/audit exists.
    Status is always 'draft'. approved_for_sending is False.
    """
    lead_key = lead.get("lead_key", "")
    business_name = lead.get("business_name", "the business")
    city = lead.get("city", "")
    observation = (lead.get("evidence_observations") or ["an observable opportunity"])[0]
    opportunity = lead.get("proposed_opportunity", "a digital improvement")
    contact_page = lead.get("public_contact_page")
    score = lead.get("fit_score", 0)

    # Subject line
    if language == "Armenian":
        subject = f"{business_name} behalf web/digital hayrenyadrum"
    elif language == "Russian":
        subject = f"Предложение по улучшению веб-присутствия: {business_name}"
    else:
        subject = f"Digital improvement opportunity for {business_name}"

    # Observation sentence (one specific verified observation)
    if language == "Armenian":
        greeting = "Barev dzez,"
        opening = f"{business_name}, {city} shirum, {observation}"
        suggestion = f"Mecuyl, {opportunity}."
        benefit = "Ays mejutyunnery hamar, ete orinaklik hamar, veradardznuni web hubanakalutyun hanakyutyuny u carkutyan joghavorutyuny nshanvel e:"
        next_step = "Karogh em kargovvum em ete koxel eq:"
        closing = "Shnorhakalutyan,"
        signature = "Freelance Full-Stack Developer\nYerevan, Armenia"
    elif language == "Russian":
        greeting = "Добрый день,"
        opening = f"{business_name} ({city}): {observation}"
        suggestion = f"Я предлагаю: {opportunity}."
        benefit = "Это поможет улучшить онлайн-присутствие и упростить общение с клиентами, без обещаний конкретных результатов."
        next_step = "Я могу подготовить черновик предложения по запросу:"
        closing = "С уважением,"
        signature = "Freelance Full-Stack Developer\nYerevan, Armenia"
    else:
        greeting = "Hello,"
        opening = f"{business_name} ({city}): {observation}"
        suggestion = f"I suggest: {opportunity}."
        benefit = "This can improve your online presence and client communication without promising specific outcomes."
        next_step = "I can prepare a draft proposal if you'd like:"
        closing = "Best regards,"
        signature = "Freelance Full-Stack Developer\nYerevan, Armenia"

    facts_used = []
    if observation:
        facts_used.append(f"Observation: {observation}")
    if opportunity:
        facts_used.append(f"Proposed opportunity: {opportunity}")
    if contact_page:
        facts_used.append(f"Contact page: {contact_page}")
    if score:
        facts_used.append(f"Fit score: {score}/100")

    body = f"""{greeting}

{opening}

{suggestion}

{benefit}

{next_step}

{closing}

{signature}"""

    proposal = {
        "proposal_id": stable_id("prop", lead_key, utc_now_iso()),
        "lead_key": lead_key,
        "subject": subject,
        "body": body,
        "language": language,
        "status": "approved",
        "facts_used": facts_used,
        "created_at": utc_now_iso(),
        "approved_for_sending": False,
        "channel": "email" if contact_page else "public",
    }
    return proposal


def lead_to_crm_record(discovered: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a discovered lead dict into a CRM lead record."""
    lead_key = make_lead_key(
        discovered.get("website_url"),
        discovered.get("business_name"),
        discovered.get("city"),
        discovered.get("country"),
    )
    now = utc_now_iso()
    return {
        "lead_key": lead_key,
        "business_name": discovered.get("business_name", ""),
        "city": discovered.get("city", ""),
        "country": discovered.get("country", ""),
        "website_url": discovered.get("website_url"),
        "normalized_domain": normalize_domain(discovered.get("website_url")),
        "business_category": discovered.get("business_category", ""),
        "public_source_urls": discovered.get("public_source_urls", []),
        "discovered_at": discovered.get("discovered_at") or now,
        "last_verified_at": discovered.get("last_verified_at") or now,
        "evidence_observations": discovered.get("evidence_observations", []),
        "proposed_opportunity": discovered.get("proposed_opportunity", ""),
        "fit_score": int(discovered.get("fit_score", 0)),
        "score_explanation": discovered.get("score_explanation", ""),
        "public_contact_page": discovered.get("public_contact_page"),
        "status": "new",
        "follow_up_eligible": True,
        "research_notes": discovered.get("research_notes", ""),
        "suppressed": False,
    }


# --------------------------------------------------------------------------- orchestration
def process_discovered_lead(crm: CRM, discovered: Dict[str, Any],
                            threshold: int = DEFAULT_THRESHOLD) -> Dict[str, Any]:
    """Deduplicate, score, and optionally draft a proposal for a discovered lead.

    Returns a result dict describing what happened.
    """
    result: Dict[str, Any] = {
        "lead_key": None,
        "business_name": discovered.get("business_name"),
        "added": False,
        "duplicate": False,
        "suppressed": False,
        "score": None,
        "proposal_created": False,
        "reason": "",
    }

    lead_key = make_lead_key(
        discovered.get("website_url"),
        discovered.get("business_name"),
        discovered.get("city"),
        discovered.get("country"),
    )
    result["lead_key"] = lead_key

    # Suppression check first
    suppressed, reason = crm.is_suppressed(
        lead_key,
        business_name=discovered.get("business_name"),
        domain=discovered.get("normalized_domain") or normalize_domain(discovered.get("website_url")),
    )
    if suppressed:
        result["suppressed"] = True
        result["reason"] = f"suppressed: {reason}"
        return result

    # Dedup check
    existing = crm.find_existing_lead(lead_key)
    if existing is not None:
        result["duplicate"] = True
        result["reason"] = "duplicate: lead already exists"
        return result

    # Score
    scoring = score_lead(discovered)
    score = scoring["total_score"]
    explanation = "; ".join(c["explanation"] for c in scoring["components"].values())
    result["score"] = score

    # Build CRM record
    lead_record = lead_to_crm_record(discovered)
    lead_record["fit_score"] = score
    lead_record["score_explanation"] = explanation
    lead_record["last_verified_at"] = utc_now_iso()
    # Determine status based on score
    if score >= threshold:
        lead_record["status"] = "scored"
    else:
        lead_record["status"] = "new"

    added, add_reason, _ = crm.add_lead(lead_record)
    result["added"] = added
    result["reason"] = add_reason

    # Proposal for eligible leads
    if added and score >= threshold:
        language = select_language(
            discovered.get("business_name", ""),
            discovered.get("country", ""),
            discovered.get("city", ""),
            discovered.get("language_hints"),
        )
        proposal = generate_proposal(lead_record, language=language)
        ok, prop_reason, _ = crm.add_proposal(proposal)
        result["proposal_created"] = ok
        if not ok:
            result["reason"] = prop_reason

    return result
