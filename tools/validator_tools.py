"""Syntax & DNS/MX record validator for target emails."""

from __future__ import annotations

import re
from typing import Any

import dns.resolver

from utils.logger import logger

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def check_syntax(email: str) -> bool:
    """Return True if email matches a pragmatic RFC-ish pattern."""
    if not email or len(email) > 254:
        return False
    return bool(_EMAIL_RE.match(email.strip()))


def check_mx_records(domain: str, timeout: float = 5.0) -> tuple[bool, str]:
    """
    Resolve MX records for a domain via dnspython.

    Returns:
        (ok, detail) where ok is True if at least one MX (or A fallback) exists.
    """
    domain = domain.strip().lower().rstrip(".")
    if not domain:
        return False, "Empty domain"

    resolver = dns.resolver.Resolver()
    resolver.lifetime = timeout

    try:
        answers = resolver.resolve(domain, "MX")
        hosts = sorted(
            ((r.preference, str(r.exchange).rstrip(".")) for r in answers),
            key=lambda x: x[0],
        )
        detail = "MX: " + ", ".join(f"{pref}:{host}" for pref, host in hosts[:5])
        return True, detail
    except dns.resolver.NXDOMAIN:
        return False, "NXDOMAIN — domain does not exist"
    except dns.resolver.NoAnswer:
        # Fallback: some domains accept mail on A/AAAA only
        try:
            resolver.resolve(domain, "A")
            return True, "No MX; A record present (implicit MX)"
        except Exception:
            return False, "No MX or A records"
    except dns.resolver.NoNameservers:
        return False, "No nameservers"
    except dns.exception.Timeout:
        return False, "DNS timeout"
    except Exception as exc:
        return False, f"DNS error: {exc}"


def validate_email(email: str) -> dict[str, Any]:
    """
    Full email validation: syntax + MX (or A-fallback).

    Returns a structured dict consumed by the verification agent.
    """
    email = (email or "").strip()
    result: dict[str, Any] = {
        "email": email,
        "syntax_valid": False,
        "mx_valid": False,
        "domain": "",
        "detail": "",
    }

    if not email:
        result["detail"] = "Empty email"
        return result

    syntax_ok = check_syntax(email)
    result["syntax_valid"] = syntax_ok
    if not syntax_ok:
        result["detail"] = "Invalid email syntax"
        logger.debug("Email syntax invalid: {}", email)
        return result

    domain = email.rsplit("@", 1)[-1]
    result["domain"] = domain
    mx_ok, detail = check_mx_records(domain)
    result["mx_valid"] = mx_ok
    result["detail"] = detail
    logger.debug("Email validation {} | syntax={} mx={} detail={}", email, syntax_ok, mx_ok, detail)
    return result
