#!/usr/bin/env python3
"""Generate one static HTML concept demo for a lead."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEADS = ROOT / "client_acquisition" / "data" / "leads.jsonl"
OUT = ROOT / "business-demos"

THEMES = [
    ("#0f172a", "#2563eb", "#f8fafc", "Inter, system-ui, sans-serif"),
    ("#111827", "#16a34a", "#f9fafb", "Georgia, serif"),
    ("#1f2937", "#ea580c", "#fff7ed", "Helvetica, Arial, sans-serif"),
    ("#0b1324", "#7c3aed", "#f5f3ff", "Trebuchet MS, sans-serif"),
    ("#172554", "#0891b2", "#ecfeff", "Verdana, sans-serif"),
]


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "business"


def load_leads() -> list[dict]:
    return [json.loads(line) for line in LEADS.read_text(encoding="utf-8").splitlines() if line.strip()]


def unique_slug(lead: dict, used: set[str]) -> str:
    base = slugify(f"{lead.get('business_name', 'business')}-{lead.get('city', '')}")
    slug = base
    n = 2
    while slug in used:
        slug = f"{base}-{n}"
        n += 1
    used.add(slug)
    return slug


def theme_for(lead: dict) -> tuple[str, str, str, str]:
    key = lead.get("lead_key") or lead.get("business_name", "")
    return THEMES[int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(THEMES)]


def esc(value) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_html(lead: dict, slug: str) -> str:
    theme = theme_for(lead)
    bg, accent, surface, font = theme
    name = esc(lead.get("business_name", "Business"))
    city = esc(lead.get("city", ""))
    country = esc(lead.get("country", ""))
    category = esc(lead.get("business_category", "Local business"))
    website = lead.get("website_url")
    contact = lead.get("public_contact_page")
    sources = lead.get("public_source_urls") or []
    observations = lead.get("evidence_observations") or []
    opportunity = esc(lead.get("proposed_opportunity", "Improve the online customer journey."))
    score = lead.get("fit_score")
    source_links = "".join(f'<li><a href="{esc(url)}" target="_blank" rel="noopener">{esc(url)}</a></li>' for url in sources)
    observation_items = "".join(f"<li>{esc(item)}</li>" for item in observations) or "<li>Public business information was verified before creating this concept.</li>"
    links = []
    if website:
        links.append(f'<a class="button secondary" href="{esc(website)}" target="_blank" rel="noopener">Current website</a>')
    if contact:
        links.append(f'<a class="button secondary" href="{esc(contact)}" target="_blank" rel="noopener">Public contact page</a>')
    link_html = "\n".join(links) or '<span class="muted">No public website or contact page was listed in the CRM record.</span>'
    score_html = f"<span>Fit score: {esc(score)}/100</span>" if score is not None else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name} | Concept Demo Website</title>
  <meta name="description" content="Unofficial concept demo website for {name}, a {category} business in {city}, {country}.">
  <style>
    :root {{
      --bg: {bg};
      --accent: {accent};
      --surface: {surface};
      --font: {font};
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: var(--font); color: #111827; background: #ffffff; line-height: 1.6; }}
    header {{ background: var(--bg); color: #ffffff; padding: 1rem 1.25rem; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 0 1.25rem; }}
    nav {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }}
    nav a {{ color: #ffffff; text-decoration: none; font-weight: 600; }}
    .hero {{ background: linear-gradient(135deg, var(--bg), var(--accent)); color: #ffffff; padding: 5rem 0; }}
    .hero h1 {{ font-size: clamp(2rem, 5vw, 4rem); margin: 0 0 1rem; }}
    .hero p {{ max-width: 760px; font-size: 1.15rem; }}
    .badge {{ display: inline-block; background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28); border-radius: 999px; padding: .35rem .85rem; margin-bottom: 1rem; }}
    section {{ padding: 4rem 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.25rem; }}
    .card {{ background: var(--surface); border: 1px solid #e5e7eb; border-radius: 1rem; padding: 1.5rem; }}
    .card h2 {{ margin-top: 0; color: var(--bg); }}
    .button {{ display: inline-block; padding: .8rem 1.1rem; border-radius: .75rem; text-decoration: none; font-weight: 700; margin: .25rem .25rem .25rem 0; }}
    .button.primary {{ background: var(--accent); color: #ffffff; }}
    .button.secondary {{ background: #ffffff; color: var(--bg); border: 1px solid #d1d5db; }}
    form {{ display: grid; gap: .75rem; }}
    input, textarea {{ width: 100%; padding: .8rem; border: 1px solid #d1d5db; border-radius: .75rem; font: inherit; }}
    textarea {{ min-height: 130px; }}
    .notice {{ background: #fffbeb; border: 1px solid #fcd34d; border-radius: .75rem; padding: 1rem; }}
    footer {{ background: #f3f4f6; padding: 2rem 0; color: #4b5563; }}
    .muted {{ color: #6b7280; }}
    @media (max-width: 640px) {{ .hero {{ padding: 3.5rem 0; }} }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <nav>
        <a href="#top">{name}</a>
        <div>
          <a href="#services">Services</a>
          <a href="#contact">Contact</a>
        </div>
      </nav>
    </div>
  </header>

  <main id="top">
    <section class="hero">
      <div class="wrap">
        <span class="badge">{category} concept demo</span>
        <h1>{name}</h1>
        <p>A clearer, faster, and more trustworthy website concept for a {category} business in {city}, {country}.</p>
        <p>{score_html}</p>
        <a class="button primary" href="#contact">Request information</a>
      </div>
    </section>

    <section id="services">
      <div class="wrap grid">
        <article class="card">
          <h2>What we verified</h2>
          <ul>{observation_items}</ul>
        </article>
        <article class="card">
          <h2>Proposed improvement</h2>
          <p>{opportunity}</p>
          <p>This concept focuses on clear service presentation, visible contact routes, and mobile-friendly navigation.</p>
        </article>
        <article class="card">
          <h2>Public sources</h2>
          <ul>{source_links or "<li>No public source URLs were recorded.</li>"}</ul>
        </article>
      </div>
    </section>

    <section id="contact">
      <div class="wrap grid">
        <article class="card">
          <h2>Contact routes</h2>
          <p>{link_html}</p>
          <p class="muted">Verified contact details should be confirmed before production use.</p>
        </article>
        <article class="card">
          <h2>Demo inquiry form</h2>
          <form onsubmit="event.preventDefault(); alert('This is a concept demo. No request was submitted.');">
            <input type="text" name="name" placeholder="Your name" required>
            <input type="email" name="email" placeholder="Your email" required>
            <textarea name="message" placeholder="Your message" required></textarea>
            <button class="button primary" type="submit">Send inquiry</button>
          </form>
        </article>
      </div>
    </section>

    <section>
      <div class="wrap">
        <div class="notice">
          <strong>Unofficial concept demo.</strong> This page was created to demonstrate a possible website redesign. It is not the official website of {name}, and no booking, payment, or contact request is submitted by this demo.
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="wrap">
      <p>Concept demo generated from verified CRM data. Business facts, contact details, and availability must be confirmed before production use.</p>
    </div>
  </footer>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, help="Zero-based lead index")
    parser.add_argument("--lead-key", type=str, help="Lead key")
    args = parser.parse_args()

    leads = load_leads()
    if args.lead_key:
        matches = [lead for lead in leads if lead.get("lead_key") == args.lead_key]
        if not matches:
            raise SystemExit(f"lead not found: {args.lead_key}")
        lead = matches[0]
    elif args.index is not None:
        if args.index < 0 or args.index >= len(leads):
            raise SystemExit(f"index out of range: {args.index}")
        lead = leads[args.index]
    else:
        raise SystemExit("provide --index or --lead-key")

    used = {p.name for p in OUT.iterdir() if p.is_dir()} if OUT.exists() else set()
    slug = unique_slug(lead, used)
    target = OUT / slug
    target.mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text(build_html(lead, slug), encoding="utf-8")
    (target / "demo-metadata.json").write_text(
        json.dumps(
            {
                "lead_key": lead.get("lead_key"),
                "business_name": lead.get("business_name"),
                "city": lead.get("city"),
                "country": lead.get("country"),
                "business_category": lead.get("business_category"),
                "website_url": lead.get("website_url"),
                "status": "completed",
                "demo_type": "static-html-concept",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(slug)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY