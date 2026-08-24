"""mmos-client-py — the drop-in MM OS auth client. See README.md."""
from .core import CurrentUser, MMOS, llm_guard, report_usage, require_role
from ._verify import TokenError

__all__ = [
    "MMOS",
    "CurrentUser",
    "require_role",
    "llm_guard",
    "report_usage",
    "TokenError",
]

__version__ = "0.1.0"
