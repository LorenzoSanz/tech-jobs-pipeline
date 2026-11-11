"""Role family of a posting, from its title.

A coarse grouping so the dashboards can offer a fixed list of roles instead of
a free-text regex. The first family whose pattern matches wins, so the order
matters: "Data Scientist" is ML before it is data, "Engineering Manager" is
management before it is engineering. An account manager is not technical
and ends up in OTHER.
"""

from __future__ import annotations

import re

OTHER = "Otros (no técnicos)"

FAMILIES: tuple[tuple[str, str], ...] = (
    ("Producto y diseño", r"product (manager|owner|lead)|\bpm\b|designer|\bux\b|\bui/ux\b"),
    ("Gestión técnica", r"(engineering|software|development|technical|data|platform|infrastructure|security|it|qa)"
                        r" (manager|director|lead)|head of (engineering|software|data|technology|it|platform|ai|ml)"
                        r"|\bcto\b|\bvp,? (of )?engineering|director,? (of )?engineering"),
    ("ML / IA", r"machine learning|\bml\b|\bai\b|\bllm|deep learning|computer vision|\bnlp\b|scientist|research engineer"),
    ("Datos", r"\bdata\b|analytics|analyst|\bbi\b|\betl\b|\bdbt\b"),
    ("DevOps / SRE / Plataforma", r"devops|\bsre\b|site reliability|platform|infrastructure|\bcloud\b|kubernetes|\bops\b"),
    ("Seguridad", r"security|appsec|pentest|\bsoc\b"),
    ("Móvil", r"\bios\b|android|mobile|flutter|react native"),
    ("QA / Test", r"\bqa\b|quality|\btest|sdet"),
    ("Embebido / Hardware", r"embedded|firmware|fpga|hardware|electronic"),
    ("Full-stack", r"full[ -]?stack"),
    ("Frontend", r"front[ -]?end|\bui engineer|react|angular|\bvue"),
    ("Backend", r"back[ -]?end|\bjava\b|python|golang|\bgo\b|node|rust|scala|kotlin|\.net|c#|ruby|php|\bapi\b"),
    ("Ingeniería (general)", r"engineer|developer|programmer|software|\bdev\b"),
)

_COMPILED = tuple((name, re.compile(pattern, re.IGNORECASE)) for name, pattern in FAMILIES)


def role_of(title: str | None) -> str:
    for name, pattern in _COMPILED:
        if title and pattern.search(title):
            return name
    return OTHER


def names() -> list[str]:
    return [name for name, _ in FAMILIES] + [OTHER]
