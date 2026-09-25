"""
Rate limiting (project brief section 22).

A single shared Limiter instance, keyed by client IP. A generous global
default applies to every route via SlowAPIMiddleware; auth.py applies
stricter limits to login/register specifically, since those are the
routes brute-force and spam-registration attempts actually target.

`enabled` is driven by settings.rate_limit_enabled (see config.py) rather
than hardcoded, specifically so the test suite can run with it off by
default (see tests/conftest.py) without dozens of logins across the test
suite spuriously tripping the limiter, while a dedicated test
(tests/test_rate_limiting.py) flips it on to verify the real behavior.
"""
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    enabled=settings.rate_limit_enabled,
)
