"""Canonical departments, and the clean-up rules for the people sheet's free-text fields.

The employee form was filled in by hand, so one department arrives under many spellings
("P-hub", "P-HUB ", "Phub") and IDs and emails carry stray zeros, dashes and typos. Role rules
match `Employee.hr_department` exactly (app/roles_io.py), so every department must be stored
under one canonical name. The mapping below is the owner's, agreed 25 Sep 2026: anything not
listed is reported, never guessed.

No personal data lives here: only department names and email-domain typos.
"""
from __future__ import annotations

import re

UNASSIGNED = "Unassigned"

CANONICAL: tuple[str, ...] = (
    "BD & Operations",
    "CXO Office",
    "EHS",
    "Finance",
    "HR",
    "IT",
    "Logistics",
    "N-Hub",
    "P-Hub",
    "P-Spoke",
    "Projects",
    "Purchase",
    "QA/QC",
    "R&D",
    "StratOps",
    "Stores",
    UNASSIGNED,
)

# normalised spelling -> canonical. Keys go through _norm() below.
_ALIASES: dict[str, str] = {
    # Business development and BD & operations are one department.
    "bd and operations": "BD & Operations",
    "bd operations": "BD & Operations",
    "business development": "BD & Operations",
    "business and development": "BD & Operations",
    "business operations": "BD & Operations",
    "business development and operations": "BD & Operations",
    "cxo office": "CXO Office",
    "cto": "CXO Office",
    "corporate": "CXO Office",
    "ehs": "EHS",
    "finance": "Finance",
    "finance operations": "Finance",
    "hr": "HR",
    "human resource": "HR",
    "human resources": "HR",
    "hr and admin": "HR",
    "hr and stores": "HR",
    "it": "IT",
    "it admin": "IT",
    "information technology": "IT",
    "logistics": "Logistics",
    "nhub": "N-Hub",
    # Production sits under P-Hub.
    "phub": "P-Hub",
    "production": "P-Hub",
    # Engineering, maintenance, instrumentation and Second Life sit under P-Spoke.
    "pspoke": "P-Spoke",
    "spoke": "P-Spoke",
    "engineering": "P-Spoke",
    "maintenance": "P-Spoke",
    "instrumentation": "P-Spoke",
    "engineering and maintenance": "P-Spoke",
    "second life": "P-Spoke",
    "2nd life": "P-Spoke",
    "project": "Projects",
    "projects": "Projects",
    "purchase": "Purchase",
    "qa and qc": "QA/QC",
    "qaqc": "QA/QC",
    "r and d": "R&D",
    "research and development": "R&D",
    "stratops": "StratOps",
    "strategy and operations": "StratOps",
    "strategy operations": "StratOps",
    # Stores and Logistics are separate departments; material management is stores.
    "stores": "Stores",
    "store": "Stores",
    "material management": "Stores",
    "materials management": "Stores",
    "materials mgmt stores": "Stores",
    "unassigned": UNASSIGNED,
}

# Spellings that map, but lose information the admin should see.
_NOTES: dict[str, str] = {
    "hr and stores": "listed as HR & Stores: stored as HR, so give any Stores access in the row itself",
}


def _norm(text: str) -> str:
    t = str(text or "").lower().replace("&", " and ").replace("/", " and ").replace("-", "")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def canonical_department(raw) -> tuple[str | None, str | None]:
    """(canonical name, note) for a typed department, or (None, reason) if it is unknown."""
    key = _norm(raw)
    if not key:
        return None, "no department given"
    for name in CANONICAL:  # the canonical spelling itself, in any case
        if _norm(name) == key:
            return name, None
    if key in _ALIASES:
        return _ALIASES[key], _NOTES.get(key)
    return None, f"unknown department {str(raw).strip()!r}"


# ── employee codes ────────────────────────────────────────────────────────────
_CODE_RE = re.compile(r"^MM[\s\-_.]*(\d+)$")


def normalize_code(raw) -> str | None:
    """`MM` + the number, no zero padding, no separators: "MM00115", "mm-115", "MM 115" and
    115.0 (a number cell) all become "MM115". Returns None when there is no usable number."""
    if raw is None:
        return None
    if isinstance(raw, float) and raw.is_integer():
        raw = int(raw)
    text = str(raw).strip().upper()
    if re.fullmatch(r"\d+(\.0+)?", text):
        digits = text.split(".")[0]
    else:
        m = _CODE_RE.match(text)
        if not m:
            return None
        digits = m.group(1)
    n = int(digits)
    return f"MM{n}" if n > 0 else None


# ── emails ────────────────────────────────────────────────────────────────────
COMPANY_DOMAIN = "m-mines.com"
_EMAIL_RE = re.compile(r"^[a-z0-9._%+\-]+@[a-z0-9\-]+(\.[a-z0-9\-]+)+$")
_DOMAIN_TYPOS = {
    "gamail.com": "gmail.com",
    "gmial.com": "gmail.com",
    "gmai.com": "gmail.com",
    "gmail.co": "gmail.com",
    "gmail.con": "gmail.com",
    "gmailcom": "gmail.com",
    "mimines.com": COMPANY_DOMAIN,
    "mmines.com": COMPANY_DOMAIN,
    "m-mines.co": COMPANY_DOMAIN,
}


def clean_email(raw) -> tuple[str | None, str | None, str | None]:
    """(email, fix, error). `fix` describes a correction that was applied; `error` means the
    value could not be used at all (email is then None)."""
    text = str(raw or "").strip()
    if not text:
        return None, None, None
    if re.search(r"[,;]", text) or text.count("@") > 1:
        return None, None, "more than one address in one cell"
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    fixes = []
    if compact != lowered:
        fixes.append("removed spaces")
    if "@" not in compact:
        return None, None, "not an email address"
    local, domain = compact.split("@", 1)
    if domain in _DOMAIN_TYPOS:
        fixes.append(f"domain {domain} → {_DOMAIN_TYPOS[domain]}")
        domain = _DOMAIN_TYPOS[domain]
    elif domain == "gmail" or domain.startswith("gmail") and "." not in domain:
        fixes.append(f"domain {domain} → gmail.com")
        domain = "gmail.com"
    email = f"{local}@{domain}"
    if not _EMAIL_RE.match(email):
        return None, None, "not an email address"
    return email, ("; ".join(fixes) or None), None


def is_company_email(email: str | None) -> bool:
    return bool(email) and email.endswith("@" + COMPANY_DOMAIN)
