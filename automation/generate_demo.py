#!/usr/bin/env python3
"""Generate one static, business-specific concept demo for a lead."""

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
    ("#0f172a", "#2563eb", "#f8fafc", "Inter, system-ui, sans-serif", "blueprint"),
    ("#111827", "#16a34a", "#f0fdf4", "Georgia, serif", "editorial"),
    ("#1f2937", "#ea580c", "#fff7ed", "Helvetica, Arial, sans-serif", "bold"),
    ("#0b1324", "#7c3aed", "#f5f3ff", "Trebuchet MS, sans-serif", "modern"),
    ("#172554", "#0891b2", "#ecfeff", "Verdana, sans-serif", "clean"),
    ("#292524", "#ca8a04", "#fefce8", "Georgia, serif", "warm"),
    ("#111827", "#e11d48", "#fff1f2", "Helvetica, Arial, sans-serif", "vibrant"),
    ("#0f172a", "#14b8a6", "#f0fdfa", "Trebuchet MS, sans-serif", "fresh"),
]

CATEGORY_PROFILES = {
    "restaurant": ("Restaurant", "Menu highlights", "Reserve a table", "Opening hours, location, and menu presentation"),
    "cafe": ("Cafe", "Menu and atmosphere", "Visit us", "Menu, hours, and local atmosphere"),
    "hotel": ("Hotel", "Rooms and amenities", "Request a booking", "Rooms, amenities, gallery, and location"),
    "dental": ("Dental clinic", "Treatments", "Request an appointment", "Services, appointment flow, and trust details"),
    "beauty": ("Beauty salon", "Services", "Book a visit", "Services, gallery, and appointment request"),
    "auto": ("Auto service", "Services", "Request service", "Services, diagnostics, and appointment request"),
    "construction": ("Construction", "Services", "Request a quote", "Services, process, and project inquiry"),
    "real estate": ("Real estate", "Listings", "Contact an agent", "Property search, listings, and inquiry flow"),
    "accounting": ("Accounting", "Services", "Book a consultation", "Services, compliance, and consultation request"),
    "law": ("Law firm", "Practice areas", "Schedule a consultation", "Practice areas, trust, and consultation request"),
    "fitness": ("Fitness", "Programs", "Join now", "Programs, schedule, and membership inquiry"),
    "veterinary": ("Veterinary clinic", "Services", "Book a visit", "Services, emergency contact, and appointment request"),
    "pharmacy": ("Pharmacy", "Products and services", "Contact pharmacy", "Products, services, and location"),
    "translation": ("Translation", "Language services", "Request a quote", "Language pairs, services, and quote request"),
    "interior": ("Interior design", "Projects", "Start a project", "Portfolio, process, and project inquiry"),
    "marketing": ("Marketing agency", "Services", "Start a project", "Services, case studies, and project inquiry"),
    "cleaning": ("Cleaning", "Services", "Request a quote", "Services, coverage area, and quote request"),
    "security": ("Security", "Services", "Request assessment", "Services, coverage, and assessment request"),
    "travel": ("Travel agency", "Tours and services", "Plan a trip", "Tours, destinations, and trip inquiry"),
    "medical": ("Medical center", "Services", "Book an appointment", "Services, doctors, and appointment request"),
    "optical": ("Optical store", "Products", "Visit store", "Frames, lenses, and store information"),
    "printing": ("Printing", "Services", "Request a quote", "Services, turnaround, and quote request"),
    "language": ("Language school", "Courses", "Enroll", "Courses, levels, and enrollment inquiry"),
    "spa": ("Spa and wellness", "Treatments", "Book a treatment", "Treatments, packages, and booking request"),
    "coworking": ("Coworking", "Spaces", "Book a tour", "Spaces, pricing, and tour request"),
    "technology": ("Technology", "Services", "Contact us", "Services, solutions, and contact request"),
}


def profile_for(category: str) -> tuple[str, str, str, str]:
    text = (category or "").lower()
    for key, value in CATEGORY_PROFILES.items():
        if key in text:
            return value
    return ("Local business", "Services", "Contact us", "Services, trust, and contact information")


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "business"


def load_leads() -> list[dict]:
    return [json.loads(line) for line in LEADS.read_text(encoding="utf-8").splitlines() if line.strip()]


def theme_for(lead: dict) -> tuple[str, str, str, str, str]:
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


def build_html(lead: dict, slug: str, force: bool = False) -> str:
    bg, accent, surface, font, motif = theme_for(lead)
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
    profile, section_title, cta, focus = profile_for(lead.get("business_category", ""))
    profile = esc(profile)
    section_title = esc(section_title)
    cta = esc(cta)
    focus = esc(focus)

    source_items = "".join(f'<li><a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(url)}</a></li>' for url in sources)
    if not source_items:
        source_items = "<li>No public source URLs were recorded.</li>"
    observation_items = "".join(f"<li>{esc(item)}</li>" for item in observations)
    if not observation_items:
        observation_items = "<li>Public business information was verified before creating this concept.</li>"

    links = []
    if website:
        links.append(f'<a class="button secondary" href="{esc(website)}" target="_blank" rel="noopener noreferrer">Current website</a>')
    if contact:
        links.append(f'<a class="button secondary" href="{esc(contact)}" target="_blank" rel="noopener noreferrer">Public contact page</a>')
    link_html = "\n".join(links) if links else '<p class="muted">No public website or contact page was listed in the CRM record.</p>'
    score_html = f"Fit score: {esc(score)}/100" if score is not None else ""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name} | {profile} Concept Demo</title>
  <meta name="description" content="Unofficial concept demo for {name}, a {profile.lower()} in {city}, {country}. Focus: {focus}.">
  <meta name="robots" content="noindex">
  <style>
    :root {{
      --bg: {bg};
      --accent: {accent};
      --surface: {surface};
      --font: {font};
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{ margin: 0; font-family: var(--font); color: #172033; background: #ffffff; line-height: 1.65; }}
    a {{ color: var(--accent); }}
    header {{ position: sticky; top: 0; z-index: 10; background: var(--bg); color: #fff; box-shadow: 0 8px 24px rgba(0,0,0,.18); }}
    .wrap {{ width: min(1180px, calc(100% - 2rem)); margin: 0 auto; }}
    nav {{ display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 1rem 0; flex-wrap: wrap; }}
    nav a {{ color: #fff; text-decoration: none; font-weight: 700; }}
    .nav-links {{ display: flex; gap: .9rem; flex-wrap: wrap; }}
    .hero {{ background: linear-gradient(135deg, var(--bg), var(--accent)); color: #fff; padding: clamp(4rem, 8vw, 7rem) 0; overflow: hidden; }}
    .hero-grid {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(260px, .8fr); gap: 2rem; align-items: center; }}
    .hero h1 {{ font-size: clamp(2.3rem, 6vw, 5rem); line-height: 1.05; margin: .5rem 0 1rem; }}
    .hero p {{ max-width: 760px; font-size: 1.12rem; }}
    .eyebrow {{ display: inline-block; background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.24); border-radius: 999px; padding: .4rem .85rem; font-size: .9rem; letter-spacing: .03em; }}
    .card-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1.25rem; }}
    .card {{ background: var(--surface); border: 1px solid #e5e7eb; border-radius: 1.25rem; padding: 1.5rem; box-shadow: 0 18px 40px rgba(15,23,42,.08); }}
    .card h2, .card h3 {{ margin-top: 0; color: var(--bg); }}
    .button {{ display: inline-flex; align-items: center; justify-content: center; gap: .4rem; padding: .85rem 1.15rem; border-radius: .85rem; text-decoration: none; font-weight: 800; margin: .25rem .25rem .25rem 0; border: 0; cursor: pointer; font: inherit; }}
    .button.primary {{ background: var(--accent); color: #fff; }}
    .button.secondary {{ background: #fff; color: var(--bg); border: 1px solid #d1d5db; }}
    .button:hover {{ transform: translateY(-1px); }}
    section {{ padding: clamp(3rem, 6vw, 5rem) 0; }}
    .section-title {{ font-size: clamp(1.7rem, 4vw, 2.6rem); margin: 0 0 1.5rem; color: var(--bg); }}
    .feature-list {{ display: grid; gap: .75rem; padding: 0; list-style: none; }}
    .feature-list li {{ background: #fff; border: 1px solid #e5e7eb; border-radius: .85rem; padding: .85rem 1rem; }}
    .visual {{ min-height: 260px; border-radius: 1.25rem; background: linear-gradient(135deg, var(--accent), var(--bg)); position: relative; overflow: hidden; }}
    .visual::after {{ content: "{profile}"; position: absolute; inset: 0; display: grid; place-items: center; color: rgba(255,255,255,.92); font-size: clamp(1.5rem, 4vw, 2.5rem); font-weight: 900; text-align: center; padding: 1rem; }}
    form {{ display: grid; gap: .85rem; }}
    label {{ font-weight: 700; font-size: .95rem; }}
    input, textarea, select {{ width: 100%; padding: .85rem; border: 1px solid #d1d5db; border-radius: .85rem; font: inherit; background: #fff; }}
    textarea {{ min-height: 130px; resize: vertical; }}
    .notice {{ background: #fffbeb; border: 1px solid #fcd34d; border-radius: 1rem; padding: 1.1rem; }}
    .trust {{ display: flex; flex-wrap: wrap; gap: .75rem; }}
    .trust span {{ background: var(--surface); border: 1px solid #e5e7eb; border-radius: 999px; padding: .4rem .8rem; font-weight: 700; }}
    footer {{ background: #f3f4f6; padding: 2rem 0; color: #4b5563; }}
    .muted {{ color: #6b7280; }}
    @media (max-width: 820px) {{ .hero-grid {{ grid-template-columns: 1fr; }} .visual {{ min-height: 180px; }} }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <nav aria-label="Main navigation">
        <a href="#top">{name}</a>
        <div class="nav-links">
          <a href="#about">About</a>
          <a href="#services">{section_title}</a>
          <a href="#contact">Contact</a>
        </div>
      </nav>
    </div>
  </header>

  <main id="top">
    <section class="hero">
      <div class="wrap hero-grid">
        <div>
          <span class="eyebrow">{profile} concept demo</span>
          <h1>{name}</h1>
          <p>A clearer, faster, and more useful website concept for a {profile.lower()} serving {city}, {country}.</p>
          <p>{score_html}</p>
          <a class="button primary" href="#contact">{cta}</a>
          <a class="button secondary" href="#services">Explore {section_title.lower()}</a>
        </div>
        <div class="visual" aria-hidden="true"></div>
      </div>
    </section>

    <section id="about">
      <div class="wrap">
        <h2 class="section-title">Why this concept is different</h2>
        <div class="card-grid">
          <article class="card">
            <h3>Verified context</h3>
            <p>The concept is based on public business information and recorded observations rather than invented claims.</p>
          </article>
          <article class="card">
            <h3>Clear next step</h3>
            <p>The primary action is visible on every screen size and leads to a simple, validated inquiry flow.</p>
          </article>
          <article class="card">
            <h3>Mobile-first structure</h3>
            <p>Navigation, content, forms, and contact actions are designed to work comfortably on phones.</p>
          </article>
        </div>
      </div>
    </section>

    <section id="services">
      <div class="wrap">
        <h2 class="section-title">{section_title}</h2>
        <div class="card-grid">
          <article class="card">
            <h3>Verified observations</h3>
            <ul class="feature-list">{observation_items}</ul>
          </article>
          <article class="card">
            <h3>Proposed improvement</h3>
            <p>{opportunity}</p>
            <p>Recommended focus: {focus}.</p>
          </article>
          <article class="card">
            <h3>Public sources</h3>
            <ul class="feature-list">{source_items}</ul>
          </article>
        </div>
      </div>
    </section>

    <section>
      <div class="wrap">
        <h2 class="section-title">Trust and contact</h2>
        <div class="card-grid">
          <article class="card">
            <h3>Available contact routes</h3>
            <div class="trust">
              {link_html}
            </div>
            <p class="muted">Contact details must be confirmed before production use.</p>
          </article>
          <article class="card">
            <h3>Service area</h3>
            <p>{city}, {country}</p>
            <p class="muted">Location information is taken from the CRM record and should be verified before publication.</p>
          </article>
        </div>
      </div>
    </section>

    <section id="contact">
      <div class="wrap card-grid">
        <article class="card">
          <h2>{cta}</h2>
          <p>Use this form to start a conversation. In this concept demo, no request is submitted to a server.</p>
          <form onsubmit="event.preventDefault(); const status=document.getElementById('form-status'); status.textContent='Demo only: no request was submitted.'; status.focus();">
            <div>
              <label for="name">Name</label>
              <input id="name" name="name" type="text" autocomplete="name" required>
            </div>
            <div>
              <label for="email">Email</label>
              <input id="email" name="email" type="email" autocomplete="email" required>
            </div>
            <div>
              <label for="phone">Phone</label>
              <input id="phone" name="phone" type="tel" autocomplete="tel">
            </div>
            <div>
              <label for="message">Message</label>
              <textarea id="message" name="message" required></textarea>
            </div>
            <button class="button primary" type="submit">Send inquiry</button>
            <p id="form-status" class="muted" role="status" aria-live="polite" tabindex="-1"></p>
          </form>
        </article>
        <article class="card">
          <h2>Production notes</h2>
          <ul class="feature-list">
            <li>Replace placeholder imagery with licensed or client-provided assets.</li>
            <li>Connect the form to an approved backend or email workflow.</li>
            <li>Confirm services, prices, hours, and contact details.</li>
            <li>Add analytics only with the client's consent.</li>
          </ul>
        </article>
      </div>
    </section>

    <section>
      <div class="wrap">
        <div class="notice">
          <strong>Unofficial concept demo.</strong> This page demonstrates a possible website redesign for {name}. It is not an official website, and no booking, payment, or contact request is submitted by this demo.
        </div>
      </div>
    </section>
  </main>

  <footer>
    <div class="wrap">
      <p>Concept demo generated from verified CRM lead data. Business facts, contact details, and availability must be confirmed before production use.</p>
    </div>
  </footer>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=int, help="Zero-based lead index")
    parser.add_argument("--lead-key", type=str, help="Lead key")
    parser.add_argument("--force", action="store_true", help="Regenerate even if a completed demo exists")
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

    if OUT.exists() and not args.force:
        for meta_path in OUT.glob("*/demo-metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("lead_key") == lead.get("lead_key"):
                print(meta_path.parent.name)
                return 0

    used = {p.name for p in OUT.iterdir() if p.is_dir()} if OUT.exists() else set()
    slug = slugify(f"{lead.get('business_name', 'business')}-{lead.get('city', '')}")
    if slug in used:
        n = 2
        while f"{slug}-{n}" in used:
            n += 1
        slug = f"{slug}-{n}"
    used.add(slug)

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
                "demo_type": "static-html-concept-v2",
                "generator_version": 2,
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