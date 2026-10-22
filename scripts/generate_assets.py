"""Gera os SVGs estáticos do perfil (banner, cards de projeto e rodapé).

Cada peça sai em duas variantes, `-dark` e `-light`, usadas pelo README com
`<picture>` para acompanhar o tema do GitHub. Tudo é SVG puro com animação
SMIL/CSS, sem fontes ou recursos externos: o GitHub serve as imagens pelo
camo, que bloqueia qualquer requisição de dentro do SVG.

Uso: uv run scripts/generate_assets.py [--stack]

`--stack` também baixa de novo as faixas de ícones de tecnologia do
skillicons.dev (licença MIT), versionadas em assets/stack/.
"""

from __future__ import annotations

import math
import sys
import textwrap
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"

SANS = "Inter, 'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', 'Fira Code', 'SFMono-Regular', Consolas, 'Liberation Mono', 'DejaVu Sans Mono', monospace"


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    panel: str
    border: str
    text: str
    muted: str
    dim: str
    accent: str
    accent2: str
    dot: str
    glow: float


DARK = Theme("dark", "#09090b", "#0f0f13", "#27272a", "#fafafa", "#a1a1aa", "#52525b",
             "#5eead4", "#34d399", "#1f1f23", 0.22)
LIGHT = Theme("light", "#ffffff", "#fafafa", "#e4e4e7", "#09090b", "#52525b", "#a1a1aa",
              "#0d9488", "#059669", "#e4e4e7", 0.14)


def svg_doc(width: int, height: int, body: str, title: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">\n'
        f"<title>{escape(title)}</title>\n{body}\n</svg>\n"
    )


def fmt(v: float) -> str:
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


# --------------------------------------------------------------------------- 3D

PHI = (1 + 5 ** 0.5) / 2


def icosahedron() -> tuple[list[tuple[float, float, float]], list[tuple[int, int]]]:
    raw = []
    for a in (-1, 1):
        for b in (-PHI, PHI):
            raw += [(0, a, b), (a, b, 0), (b, 0, a)]
    norm = math.sqrt(1 + PHI**2)
    verts = [(x / norm, y / norm, z / norm) for x, y, z in raw]
    edges = [
        (i, j)
        for i in range(len(raw))
        for j in range(i + 1, len(raw))
        if abs(math.dist(raw[i], raw[j]) - 2) < 1e-9
    ]
    return verts, edges


def rotate(p, ay: float, ax: float):
    x, y, z = p
    x, z = x * math.cos(ay) + z * math.sin(ay), -x * math.sin(ay) + z * math.cos(ay)
    y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)
    return x, y, z


def wireframe(t: Theme, cx: float, cy: float, radius: float, frames: int = 96, dur: float = 24) -> str:
    """Icosaedro girando em 3D: cada quadro é projetado em perspectiva e vira um
    valor de <animate>, com opacidade e raio dos nós pela profundidade."""
    verts, edges = icosahedron()
    proj: list[list[tuple[float, float, float]]] = []
    for f in range(frames + 1):
        u = f / frames
        ay = 2 * math.pi * u + 0.55
        ax = 0.42 + 0.22 * math.sin(2 * math.pi * u)
        row = []
        for v in verts:
            x, y, z = rotate(v, ay, ax)
            k = 3.2 / (3.2 - z)
            row.append((cx + radius * x * k, cy - radius * y * k, z))
        proj.append(row)

    def anim(attr: str, values: list[str]) -> str:
        return (f'<animate attributeName="{attr}" dur="{dur}s" repeatCount="indefinite" '
                f'values="{";".join(values)}"/>')

    out = [f'<g stroke="{t.accent}" stroke-linecap="round" fill="none">']
    for i, j in edges:
        cols = {"x1": [], "y1": [], "x2": [], "y2": [], "stroke-opacity": []}
        for row in proj:
            (x1, y1, z1), (x2, y2, z2) = row[i], row[j]
            cols["x1"].append(fmt(x1))
            cols["y1"].append(fmt(y1))
            cols["x2"].append(fmt(x2))
            cols["y2"].append(fmt(y2))
            cols["stroke-opacity"].append(f"{0.12 + 0.68 * ((z1 + z2) / 2 + 1) / 2:.2f}")
        first = proj[0]
        out.append(
            f'<line x1="{fmt(first[i][0])}" y1="{fmt(first[i][1])}" x2="{fmt(first[j][0])}" '
            f'y2="{fmt(first[j][1])}" stroke-width="1.6">'
            + "".join(anim(k, v) for k, v in cols.items())
            + "</line>"
        )
    out.append("</g>")
    out.append(f'<g fill="{t.accent}" filter="url(#node-glow)">')
    for i in range(len(verts)):
        cxs = [fmt(row[i][0]) for row in proj]
        cys = [fmt(row[i][1]) for row in proj]
        rs = [fmt(2.2 + 3.2 * (row[i][2] + 1) / 2) for row in proj]
        ops = [f"{0.25 + 0.75 * (row[i][2] + 1) / 2:.2f}" for row in proj]
        out.append(
            f'<circle cx="{cxs[0]}" cy="{cys[0]}" r="{rs[0]}">'
            + anim("cx", cxs) + anim("cy", cys) + anim("r", rs) + anim("fill-opacity", ops)
            + "</circle>"
        )
    out.append("</g>")
    return "\n".join(out)


# ----------------------------------------------------------------------- typing

def typing(t: Theme, x: float, y: float, roles: list[str], size: int = 22) -> str:
    """Digita e apaga cada frase em sequência. O recorte de cada frase cresce
    um caractere por vez (calcMode discrete); textLength fixa a largura para
    o cursor acompanhar mesmo se a fonte monoespaçada de fallback variar."""
    cw = size * 0.6
    type_dt, erase_dt, hold, gap = 0.075, 0.028, 2.2, 0.45
    events: list[tuple[float, int, int]] = []
    now = 0.0
    for r, role in enumerate(roles):
        for n in range(len(role) + 1):
            events.append((now, r, n))
            now += type_dt
        now += hold
        for n in range(len(role) - 1, -1, -1):
            events.append((now, r, n))
            now += erase_dt
        now += gap
    total = now
    key_times = ";".join(f"{e[0] / total:.5f}" for e in events)
    head = f'dur="{total:.2f}s" repeatCount="indefinite" calcMode="discrete" keyTimes="{key_times}"'

    out = []
    for r, role in enumerate(roles):
        base = fmt(len(role) * cw) if r == 0 else "0"
        widths = ";".join(fmt(n * cw if er == r else 0) for _, er, n in events)
        out.append(
            f'<clipPath id="type-{r}"><rect x="{fmt(x)}" y="{fmt(y - size)}" width="{base}" height="{size * 1.5}">'
            f'<animate attributeName="width" {head} values="{widths}"/></rect></clipPath>'
            f'<text x="{fmt(x)}" y="{fmt(y)}" clip-path="url(#type-{r})" font-family="{MONO}" '
            f'font-size="{size}" fill="{t.text}" textLength="{fmt(len(role) * cw)}" '
            f'lengthAdjust="spacing" xml:space="preserve">{escape(role)}</text>'
        )
    cursor_x = ";".join(fmt(x + n * cw + 2) for _, _, n in events)
    out.append(
        f'<rect x="{fmt(x + len(roles[0]) * cw + 2)}" y="{fmt(y - size * 0.82)}" width="{fmt(cw * 0.55)}" height="{fmt(size * 1.02)}" '
        f'fill="{t.accent}"><animate attributeName="x" {head} values="{cursor_x}"/>'
        f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="1s" repeatCount="indefinite"/></rect>'
    )
    return "\n".join(out)


# ----------------------------------------------------------------------- header

def header(t: Theme) -> str:
    w, h = 1200, 400
    roles = [
        "Desenvolvedor Full Stack Sênior",
        "Engenheiro de Computação · UFC",
        "Next.js · Node.js · Python · Kubernetes",
        "software, hardware e infraestrutura",
        "do código à operação",
    ]
    body = f"""
<defs>
  <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1.2" fill="{t.dot}"/>
  </pattern>
  <radialGradient id="glow" cx="80%" cy="35%" r="55%">
    <stop offset="0" stop-color="{t.accent}" stop-opacity="{t.glow}"/>
    <stop offset="1" stop-color="{t.accent}" stop-opacity="0"/>
  </radialGradient>
  <linearGradient id="name-grad" x1="0" x2="1">
    <stop offset="0" stop-color="{t.accent}"/>
    <stop offset="1" stop-color="{t.accent2}"/>
  </linearGradient>
  <filter id="node-glow" x="-100%" y="-100%" width="300%" height="300%">
    <feGaussianBlur stdDeviation="2.4" result="b"/>
    <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
  </filter>
  <clipPath id="frame"><rect width="{w}" height="{h}" rx="18"/></clipPath>
</defs>
<style>
  .pulse {{ animation: pulse 2s ease-in-out infinite; transform-origin: 69px 346px; }}
  @keyframes pulse {{ 0%,100% {{ opacity: .35; transform: scale(1); }} 50% {{ opacity: 0; transform: scale(2.4); }} }}
</style>
<g clip-path="url(#frame)">
  <rect width="{w}" height="{h}" fill="{t.bg}"/>
  <rect width="{w}" height="{h}" fill="url(#dots)"/>
  <rect width="{w}" height="{h}" fill="url(#glow)"/>
</g>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="18" fill="none" stroke="{t.border}"/>

<g>
  <rect x="56" y="54" width="196" height="30" rx="15" fill="{t.panel}" stroke="{t.border}"/>
  <text x="74" y="74" font-family="{MONO}" font-size="14" font-weight="700" fill="{t.text}">olá, sou o Inácio</text>
</g>
<text x="54" y="160" font-family="{SANS}" font-size="62" font-weight="800" letter-spacing="-2" fill="{t.text}">Inácio Rodrigues</text>
<text x="54" y="230" font-family="{SANS}" font-size="62" font-weight="800" letter-spacing="-2" fill="url(#name-grad)">de Matos Galvão</text>
<g>
  <text x="56" y="292" font-family="{MONO}" font-size="22" font-weight="700" fill="{t.accent}">$</text>
  {typing(t, 82, 292, roles)}
</g>
<g>
  <circle class="pulse" cx="69" cy="346" r="5" fill="{t.accent2}"/>
  <circle cx="69" cy="346" r="5" fill="{t.accent2}"/>
  <text x="84" y="351" font-family="{MONO}" font-size="14" fill="{t.muted}">disponível para novos projetos  ·  Brasil  ·  inaciorodrigues.dev.br</text>
</g>

<ellipse cx="960" cy="200" rx="205" ry="54" fill="none" stroke="{t.accent}" stroke-opacity=".18" transform="rotate(-14 960 200)"/>
<g transform="rotate(-14 960 200)">
  <circle r="4" fill="{t.accent2}" filter="url(#node-glow)">
    <animateMotion dur="9s" repeatCount="indefinite" path="M755 200 a205 54 0 1 0 410 0 a205 54 0 1 0 -410 0"/>
  </circle>
</g>
{wireframe(t, 960, 200, 128)}
"""
    return svg_doc(w, h, body, "Inácio Rodrigues de Matos Galvão — Desenvolvedor Full Stack Sênior e Engenheiro de Computação")


# ------------------------------------------------------------------------ cards

ICONS = {
    # Ícones Lucide (lucide.dev, licença ISC), viewBox 24x24.
    "joystick": '<path d="M21 17a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v2a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2Z"/>'
                '<path d="M6 15v-2"/><path d="M12 15V9"/><circle cx="12" cy="6" r="3"/>',
    "zap": '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7'
           'a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    "graduation-cap": '<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08'
                      'a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z"/><path d="M22 10v6"/>'
                      '<path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>',
    "landmark": '<line x1="3" x2="21" y1="22" y2="22"/><line x1="6" x2="6" y1="18" y2="11"/>'
                '<line x1="10" x2="10" y1="18" y2="11"/><line x1="14" x2="14" y1="18" y2="11"/>'
                '<line x1="18" x2="18" y1="18" y2="11"/><polygon points="12 2 20 7 4 7"/>',
    "arrow": '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
    "globe": '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'
             '<path d="M2 12h20"/>',
    "mail": '<rect width="20" height="16" x="2" y="4" rx="2"/><path d="m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7"/>',
    "linkedin": '<path d="M16 8a6 6 0 0 1 6 6v7h-4v-7a2 2 0 0 0-2-2 2 2 0 0 0-2 2v7h-4v-7a6 6 0 0 1 6-6z"/>'
                '<rect width="4" height="12" x="2" y="9"/><circle cx="4" cy="4" r="2"/>',
}


@dataclass(frozen=True)
class Project:
    slug: str
    icon: str
    title: str
    meta: str
    status: str
    live: bool
    description: str
    tags: tuple[str, ...]


PROJECTS = [
    Project("teleoperacao", "joystick", "Teleoperação com Force Feedback", "TCC · UFC · 2026",
            "concluído", False,
            "Controle remoto em tempo real com UDP de baixa latência, integrando Raspberry Pi, "
            "ESP32, telemetria, vídeo ao vivo e interface háptica com force feedback.",
            ("Python", "Raspberry Pi", "ESP32", "UDP", "OpenCV")),
    Project("beq-energia", "zap", "Plataformas B&Q Energia", "2024 — atual · Dev. de Sistemas Sênior",
            "em produção", True,
            "Aplicações críticas de inspeções, gestão de colaboradores e metas, em arquitetura "
            "multi-cluster Kubernetes com alta disponibilidade e práticas de DevOps.",
            ("TypeScript", "Next.js", "Node.js", "PostgreSQL", "Kubernetes")),
    Project("neuroarq", "graduation-cap", "NeuroArq Academy", "2024 — atual · Full Stack",
            "em produção", True,
            "Desenvolvimento e evolução das plataformas educacionais da NeuroArq, com foco em "
            "aplicações performáticas, pagamentos e soluções internas modernas.",
            ("TypeScript", "Next.js", "PostgreSQL", "Stripe")),
    Project("bcm-promotora", "landmark", "BCM Promotora", "Cliente · atual",
            "em produção", True,
            "Site institucional e sistema interno de propostas de crédito consignado, com "
            "parceiros bancários e acompanhamento do fluxo comercial.",
            ("Next.js", "TypeScript", "Tailwind CSS", "Auth", "Dashboard")),
]


def card(t: Theme, p: Project) -> str:
    w, h = 600, 236
    lines = textwrap.wrap(p.description, 66)
    desc = "".join(
        f'<text x="28" y="{118 + i * 23}" font-family="{SANS}" font-size="15" fill="{t.muted}">{escape(l)}</text>'
        for i, l in enumerate(lines)
    )
    chips, cx = [], 28.0
    for tag in p.tags:
        cw = len(tag) * 7.3 + 22
        chips.append(
            f'<rect x="{fmt(cx)}" y="184" width="{fmt(cw)}" height="26" rx="13" fill="{t.accent}" '
            f'fill-opacity=".08" stroke="{t.accent}" stroke-opacity=".35"/>'
            f'<text x="{fmt(cx + cw / 2)}" y="201.5" text-anchor="middle" font-family="{MONO}" '
            f'font-size="12" fill="{t.accent}">{escape(tag)}</text>'
        )
        cx += cw + 8
    status_w = len(p.status) * 7.3 + 34
    sx = w - 28 - status_w
    dot = t.accent2 if p.live else t.dim
    pulse = (
        f'<circle cx="{fmt(sx + 14)}" cy="40" r="4" fill="{dot}">'
        '<animate attributeName="r" values="4;9;4" dur="2s" repeatCount="indefinite"/>'
        '<animate attributeName="fill-opacity" values=".5;0;.5" dur="2s" repeatCount="indefinite"/></circle>'
        if p.live else ""
    )
    body = f"""
<defs>
  <linearGradient id="shine" x1="0" x2="1" gradientUnits="objectBoundingBox">
    <stop offset="0" stop-color="{t.accent}" stop-opacity="0"/>
    <stop offset=".5" stop-color="{t.accent}" stop-opacity=".9"/>
    <stop offset="1" stop-color="{t.accent}" stop-opacity="0"/>
    <animateTransform attributeName="gradientTransform" type="translate" values="-1 0;1 0" dur="4.5s" repeatCount="indefinite"/>
  </linearGradient>
  <pattern id="dots" width="20" height="20" patternUnits="userSpaceOnUse">
    <circle cx="2" cy="2" r="1" fill="{t.dot}"/>
  </pattern>
  <clipPath id="frame"><rect width="{w}" height="{h}" rx="14"/></clipPath>
</defs>
<g clip-path="url(#frame)">
  <rect width="{w}" height="{h}" fill="{t.panel}"/>
  <rect x="{w - 220}" width="220" height="{h}" fill="url(#dots)" opacity=".8"/>
  <rect width="{w}" height="2" fill="url(#shine)"/>
</g>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="14" fill="none" stroke="{t.border}"/>
<rect x="28" y="26" width="46" height="46" rx="11" fill="{t.accent}" fill-opacity=".1" stroke="{t.accent}" stroke-opacity=".3"/>
<g transform="translate(39 37)" fill="none" stroke="{t.accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{ICONS[p.icon]}</g>
<text x="90" y="46" font-family="{SANS}" font-size="20" font-weight="700" fill="{t.text}">{escape(p.title)}</text>
<text x="90" y="68" font-family="{MONO}" font-size="12.5" fill="{t.muted}">{escape(p.meta)}</text>
<rect x="{fmt(sx)}" y="27" width="{fmt(status_w)}" height="26" rx="13" fill="{t.bg}" stroke="{t.border}"/>
{pulse}
<circle cx="{fmt(sx + 14)}" cy="40" r="4" fill="{dot}"/>
<text x="{fmt(sx + 25)}" y="44.5" font-family="{MONO}" font-size="12" fill="{t.muted}">{escape(p.status)}</text>
{desc}
{''.join(chips)}
"""
    return svg_doc(w, h, body, f"{p.title} — {p.meta}")


# ---------------------------------------------------------------------- contato

CONTACTS = [
    ("site", "globe", "inaciorodrigues.dev.br"),
    ("linkedin", "linkedin", "LinkedIn"),
    ("email", "mail", "E-mail"),
]


def button(t: Theme, icon: str, label: str) -> str:
    h = 44
    tw = len(label) * 8.4
    w = round(tw + 98)
    body = f"""
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{h / 2}" fill="{t.panel}" stroke="{t.border}"/>
<circle cx="{h / 2}" cy="{h / 2}" r="15" fill="{t.accent}" fill-opacity=".12"/>
<g transform="translate({h / 2 - 9} {h / 2 - 9}) scale(.75)" fill="none" stroke="{t.accent}" stroke-width="2"
   stroke-linecap="round" stroke-linejoin="round">{ICONS[icon]}</g>
<text x="{h + 4}" y="{h / 2 + 5}" font-family="{MONO}" font-size="14" fill="{t.text}" textLength="{fmt(tw)}" lengthAdjust="spacing">{escape(label)}</text>
<g transform="translate({w - 34} {h / 2 - 7}) scale(.58)" fill="none" stroke="{t.dim}" stroke-width="2.4"
   stroke-linecap="round" stroke-linejoin="round">{ICONS["arrow"]}</g>
"""
    return svg_doc(w, h, body, label)


# ----------------------------------------------------------------------- footer

def wave(width: float, base: float, amp: float, period: float, bottom: float) -> str:
    """Senoide (curvas Q por meio período) com largura de um período a mais que
    `width`, para deslizar `period` px em loop sem emenda visível."""
    half = period / 2
    d = [f"M0 {fmt(base)}"]
    x, up = 0.0, True
    while x < width + period:
        d.append(f"Q{fmt(x + half / 2)} {fmt(base - amp if up else base + amp)} {fmt(x + half)} {fmt(base)}")
        x += half
        up = not up
    return " ".join(d) + f" V{fmt(bottom)} H0 Z"


def footer(t: Theme) -> str:
    w, h = 1200, 170
    layers = []
    for base, amp, period, op, dur in [(112, 12, 520, 0.10, 14), (124, 10, 400, 0.16, 10), (138, 8, 300, 0.28, 7)]:
        layers.append(
            f'<path d="{wave(w, base, amp, period, h)}" fill="{t.accent}" fill-opacity="{op}">'
            f'<animateTransform attributeName="transform" type="translate" values="0 0;-{period} 0" '
            f'dur="{dur}s" repeatCount="indefinite"/></path>'
        )
    body = f"""
<defs><clipPath id="frame"><rect width="{w}" height="{h}" rx="18"/></clipPath></defs>
<g clip-path="url(#frame)">
  <rect width="{w}" height="{h}" fill="{t.bg}"/>
  {''.join(layers)}
</g>
<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="18" fill="none" stroke="{t.border}"/>
<text x="{w / 2}" y="50" text-anchor="middle" font-family="{MONO}" font-size="20" font-weight="700" fill="{t.text}"><tspan fill="{t.accent}">inacio</tspan>.dev</text>
<text x="{w / 2}" y="78" text-anchor="middle" font-family="{MONO}" font-size="14" fill="{t.muted}">construindo software, hardware e infraestrutura</text>
"""
    return svg_doc(w, h, body, "inacio.dev — construindo software, hardware e infraestrutura")


STACK = {
    "linguagens": "ts,js,py,c,bash",
    "frontend": "nextjs,react,angular,astro,tailwind",
    "backend": "nodejs,fastapi,django,postgres,redis",
    "infra": "docker,kubernetes,githubactions,linux,vercel,git",
    "hardware": "raspberrypi,arduino,opencv",
}


def fetch_stack() -> None:
    (OUT / "stack").mkdir(parents=True, exist_ok=True)
    for group, icons in STACK.items():
        for theme in ("dark", "light"):
            url = f"https://skillicons.dev/icons?i={icons}&theme={theme}"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                (OUT / "stack" / f"{group}-{theme}.svg").write_bytes(resp.read())


def main() -> None:
    (OUT / "projects").mkdir(parents=True, exist_ok=True)
    for t in (DARK, LIGHT):
        (OUT / f"header-{t.name}.svg").write_text(header(t), encoding="utf-8")
        (OUT / f"footer-{t.name}.svg").write_text(footer(t), encoding="utf-8")
        for slug, icon, label in CONTACTS:
            (OUT / "contact").mkdir(exist_ok=True)
            (OUT / "contact" / f"{slug}-{t.name}.svg").write_text(button(t, icon, label), encoding="utf-8")
        for p in PROJECTS:
            (OUT / "projects" / f"{p.slug}-{t.name}.svg").write_text(card(t, p), encoding="utf-8")
    if "--stack" in sys.argv:
        fetch_stack()
    print(f"SVGs gerados em {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
