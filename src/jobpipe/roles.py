"""Role family of a posting, from its title.

A coarse grouping so the dashboards can offer a fixed list of roles instead of
a free-text regex. The first family whose pattern matches wins, so the order
matters: "Data Scientist" is ML before it is data, "Engineering Manager" is
management before it is engineering. An account manager is not technical
and ends up in OTHER.

The warehouse stores the key; labels are for the dashboards, in English and
Spanish.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Family:
    key: str
    en: str
    es: str
    pattern: str = ""

    def label(self, lang: str) -> str:
        return self.es if lang == "es" else self.en


FAMILIES: tuple[Family, ...] = (
    Family("product", "Product & design", "Producto y diseño",
           r"product (manager|owner|lead)|\bpm\b|designer|\bux\b|\bui/ux\b"),
    Family("eng_management", "Engineering management", "Gestión técnica",
           r"(engineering|software|development|technical|data|platform|infrastructure|security|it|qa)"
           r" (manager|director|lead)|head of (engineering|software|data|technology|it|platform|ai|ml)"
           r"|\bcto\b|\bvp,? (of )?engineering|director,? (of )?engineering"),
    Family("ml", "ML / AI", "ML / IA",
           r"machine learning|\bml\b|\bai\b|\bllm|deep learning|computer vision|\bnlp\b|scientist|research engineer"),
    Family("data", "Data", "Datos", r"\bdata\b|analytics|analyst|\bbi\b|\betl\b|\bdbt\b"),
    Family("devops", "DevOps / SRE / Platform", "DevOps / SRE / Plataforma",
           r"devops|\bsre\b|site reliability|platform|infrastructure|\bcloud\b|kubernetes|\bops\b"),
    Family("security", "Security", "Seguridad", r"security|appsec|pentest|\bsoc\b"),
    Family("mobile", "Mobile", "Móvil", r"\bios\b|android|mobile|flutter|react native"),
    Family("qa", "QA / Testing", "QA / Test", r"\bqa\b|quality|\btest|sdet"),
    Family("embedded", "Embedded / Hardware", "Embebido / Hardware",
           r"embedded|firmware|fpga|hardware|electronic|electrical|mechanical|industrial|manufacturing"
           r"|civil|chemical|controls engineer|\bait\b"),
    Family("fullstack", "Full-stack", "Full-stack", r"full[ -]?stack"),
    Family("frontend", "Frontend", "Frontend", r"front[ -]?end|\bui engineer|react|angular|\bvue"),
    Family("backend", "Backend", "Backend",
           r"back[ -]?end|\bjava\b|python|golang|\bgo\b|node|rust|scala|kotlin|\.net|c#|ruby|php|\bapi\b"),
    Family("engineering", "Engineering (general)", "Ingeniería (general)",
           r"engineer|developer|programmer|software|\bdev\b"),
)  # fmt: skip
OTHER = Family("other", "Other (non-tech)", "Otros (no técnicos)")
ALL = (*FAMILIES, OTHER)

_COMPILED = tuple((family.key, re.compile(family.pattern, re.IGNORECASE)) for family in FAMILIES)


def role_of(title: str | None) -> str:
    """Key of the first family whose pattern matches the title."""
    for key, pattern in _COMPILED:
        if title and pattern.search(title):
            return key
    return OTHER.key
