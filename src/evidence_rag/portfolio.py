"""Static portfolio generation and deployment integrations."""

from __future__ import annotations

import base64
import html
import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any

import httpx


class PortfolioError(ValueError):
    """Raised when portfolio input or a deployment request is invalid."""


class DeploymentError(RuntimeError):
    """Raised when a hosting provider rejects a deployment."""


@dataclass(frozen=True)
class Project:
    title: str
    description: str
    url: str = ""


@dataclass(frozen=True)
class Portfolio:
    name: str
    headline: str
    bio: str
    email: str = ""
    location: str = ""
    avatar_url: str = ""
    github_url: str = ""
    linkedin_url: str = ""
    skills: list[str] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    accent_color: str = "#6d5dfc"


@dataclass(frozen=True)
class DeploymentResult:
    provider: str
    url: str
    deployment_id: str


_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$")
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


def validate_slug(value: str) -> str:
    slug = value.strip().lower()
    if not _SLUG_PATTERN.fullmatch(slug):
        raise PortfolioError(
            "Sayt nomi kichik lotin harflari, raqamlar va chiziqchalardan iborat bo‘lishi kerak."
        )
    return slug


def parse_projects(value: str) -> list[Project]:
    """Parse one `title | description | URL` project per line."""
    projects: list[Project] = []
    for line_number, line in enumerate(value.splitlines(), 1):
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise PortfolioError(
                f"Loyiha {line_number}-qatorda `Nomi | Tavsifi | URL` formatida bo‘lishi kerak."
            )
        projects.append(Project(parts[0], parts[1], parts[2] if len(parts) == 3 else ""))
    return projects


def _safe_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not value.lower().startswith(("https://", "http://")):
        raise PortfolioError(f"URL http:// yoki https:// bilan boshlanishi kerak: {value}")
    return html.escape(value, quote=True)


def render_portfolio(portfolio: Portfolio) -> str:
    """Render a self-contained, safely escaped portfolio document."""
    if not portfolio.name.strip() or not portfolio.headline.strip() or not portfolio.bio.strip():
        raise PortfolioError("Ism, kasbiy sarlavha va o‘zingiz haqingizda ma’lumot majburiy.")
    if not _COLOR_PATTERN.fullmatch(portfolio.accent_color):
        raise PortfolioError("Rang #RRGGBB formatida bo‘lishi kerak.")

    esc = lambda value: html.escape(value.strip())
    avatar = _safe_url(portfolio.avatar_url)
    github = _safe_url(portfolio.github_url)
    linkedin = _safe_url(portfolio.linkedin_url)
    project_cards = []
    for project in portfolio.projects:
        url = _safe_url(project.url)
        link = f'<a href="{url}" target="_blank" rel="noopener noreferrer">Ko‘rish →</a>' if url else ""
        project_cards.append(
            f'<article class="card"><h3>{esc(project.title)}</h3>'
            f'<p>{esc(project.description)}</p>{link}</article>'
        )
    skill_tags = "".join(f"<li>{esc(skill)}</li>" for skill in portfolio.skills if skill.strip())
    social_links = []
    if portfolio.email.strip():
        social_links.append(f'<a href="mailto:{html.escape(portfolio.email.strip(), quote=True)}">Email</a>')
    if github:
        social_links.append(f'<a href="{github}" target="_blank" rel="noopener noreferrer">GitHub</a>')
    if linkedin:
        social_links.append(f'<a href="{linkedin}" target="_blank" rel="noopener noreferrer">LinkedIn</a>')
    avatar_markup = f'<img class="avatar" src="{avatar}" alt="{esc(portfolio.name)}">' if avatar else ""

    return f"""<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{esc(portfolio.headline)}">
  <title>{esc(portfolio.name)} — Portfolio</title>
  <style>
    :root {{--accent:{portfolio.accent_color};--ink:#151626;--muted:#666b80;--surface:#fff}}
    * {{box-sizing:border-box}} body {{margin:0;font-family:Inter,ui-sans-serif,system-ui,sans-serif;color:var(--ink);background:#f5f5fa;line-height:1.65}}
    main {{width:min(980px,calc(100% - 32px));margin:auto}} header {{min-height:70vh;display:grid;place-content:center;padding:72px 0}}
    .hero {{display:grid;grid-template-columns:1fr auto;gap:48px;align-items:center}} .eyebrow {{color:var(--accent);font-weight:750;letter-spacing:.08em;text-transform:uppercase}}
    h1 {{font-size:clamp(3rem,9vw,6.7rem);line-height:.95;margin:.12em 0}} h2 {{font-size:2rem;margin-top:0}} h3 {{margin-top:0}}
    .lead {{font-size:clamp(1.2rem,3vw,1.75rem);color:var(--muted);max-width:720px}} .bio {{max-width:720px;font-size:1.08rem}}
    .avatar {{width:190px;height:190px;border-radius:40%;object-fit:cover;box-shadow:18px 18px 0 var(--accent)}}
    section {{padding:56px 0}} .skills {{display:flex;flex-wrap:wrap;gap:10px;padding:0;list-style:none}}
    .skills li {{padding:8px 14px;border:1px solid #ddddea;border-radius:999px;background:var(--surface)}}
    .grid {{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px}} .card {{padding:24px;background:var(--surface);border-radius:18px;box-shadow:0 12px 35px #24243b0d}}
    a {{color:var(--accent);font-weight:700;text-decoration:none}} .links {{display:flex;gap:22px;flex-wrap:wrap}}
    footer {{padding:36px 0 56px;color:var(--muted);border-top:1px solid #ddddea}}
    @media(max-width:650px) {{.hero {{grid-template-columns:1fr}} .avatar {{order:-1;width:130px;height:130px}}}}
  </style>
</head>
<body>
  <main>
    <header><div class="hero"><div><div class="eyebrow">{esc(portfolio.location) or 'Portfolio'}</div><h1>{esc(portfolio.name)}</h1><p class="lead">{esc(portfolio.headline)}</p></div>{avatar_markup}</div></header>
    <section><h2>Men haqimda</h2><p class="bio">{esc(portfolio.bio)}</p></section>
    {f'<section><h2>Ko‘nikmalar</h2><ul class="skills">{skill_tags}</ul></section>' if skill_tags else ''}
    {f'<section><h2>Loyihalar</h2><div class="grid">{"".join(project_cards)}</div></section>' if project_cards else ''}
    {f'<section><h2>Bog‘lanish</h2><div class="links">{"".join(social_links)}</div></section>' if social_links else ''}
    <footer>© {esc(portfolio.name)} · Hujjat AI bilan yaratildi</footer>
  </main>
</body>
</html>"""


def portfolio_zip(document: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("index.html", document)
    return buffer.getvalue()


def _error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail: Any = payload.get("error", payload)
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("detail") or detail.get("code") or detail)
        return str(detail)
    except ValueError:
        return response.text[:300] or f"HTTP {response.status_code}"


def deploy_to_vercel(
    document: str,
    token: str,
    project_name: str,
    *,
    team_id: str = "",
    client: httpx.Client | None = None,
) -> DeploymentResult:
    slug = validate_slug(project_name)
    if not token.strip():
        raise PortfolioError("Vercel tokenini kiriting.")
    request_client = client or httpx.Client(timeout=30)
    params = {"teamId": team_id.strip()} if team_id.strip() else None
    payload = {
        "name": slug,
        "target": "production",
        "files": [{
            "file": "index.html",
            "data": base64.b64encode(document.encode()).decode(),
            "encoding": "base64",
        }],
        "projectSettings": {"framework": None},
    }
    try:
        response = request_client.post(
            "https://api.vercel.com/v13/deployments",
            params=params,
            headers={"Authorization": f"Bearer {token.strip()}"},
            json=payload,
        )
    except httpx.HTTPError as error:
        raise DeploymentError(f"Vercel bilan bog‘lanib bo‘lmadi: {error}") from error
    if response.is_error:
        raise DeploymentError(f"Vercel deploy xatosi: {_error_message(response)}")
    data = response.json()
    url = data.get("url") or next(iter(data.get("alias") or []), "")
    if not url:
        raise DeploymentError("Vercel javobida sayt manzili topilmadi.")
    if not str(url).startswith("http"):
        url = f"https://{url}"
    return DeploymentResult("Vercel", str(url), str(data.get("id", "")))


def deploy_to_netlify(
    document: str,
    token: str,
    site_name: str,
    *,
    client: httpx.Client | None = None,
) -> DeploymentResult:
    slug = validate_slug(site_name)
    if not token.strip():
        raise PortfolioError("Netlify tokenini kiriting.")
    request_client = client or httpx.Client(timeout=30)
    headers = {"Authorization": f"Bearer {token.strip()}"}
    try:
        site_response = request_client.post(
            "https://api.netlify.com/api/v1/sites", headers=headers, json={"name": slug}
        )
        if site_response.is_error:
            raise DeploymentError(f"Netlify sayt yaratish xatosi: {_error_message(site_response)}")
        site = site_response.json()
        deploy_response = request_client.post(
            f"https://api.netlify.com/api/v1/sites/{site['id']}/deploys",
            headers={**headers, "Content-Type": "application/zip"},
            content=portfolio_zip(document),
        )
    except httpx.HTTPError as error:
        raise DeploymentError(f"Netlify bilan bog‘lanib bo‘lmadi: {error}") from error
    if deploy_response.is_error:
        raise DeploymentError(f"Netlify deploy xatosi: {_error_message(deploy_response)}")
    deploy = deploy_response.json()
    url = deploy.get("ssl_url") or deploy.get("deploy_ssl_url") or site.get("ssl_url") or site.get("url")
    if not url:
        raise DeploymentError("Netlify javobida sayt manzili topilmadi.")
    return DeploymentResult("Netlify", str(url), str(deploy.get("id", "")))
