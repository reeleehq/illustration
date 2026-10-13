"""Configuration: XDG directories and package-wide defaults (the SSOT).

All tunable constants live here so the rest of the package never hardcodes a
magic number. Directories follow the XDG base-directory convention with
per-package environment overrides, mirroring the ecosystem's ``ir``/``aix``
idiom:

================  ===================================  ============================
Purpose           Environment override                 Fallback
================  ===================================  ============================
config            ``ILLUSTRATION_CONFIG_DIR``           ``$XDG_CONFIG_HOME``/illustration
data (durable)    ``ILLUSTRATION_DATA_DIR``             ``$XDG_DATA_HOME``/illustration
cache (regen.)    ``ILLUSTRATION_CACHE_DIR``            ``$XDG_CACHE_HOME``/illustration
================  ===================================  ============================

>>> p = cache_dir()                          # doctest: +ELLIPSIS
>>> p.name
'illustration'
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

__all__ = [
    "config_dir",
    "data_dir",
    "cache_dir",
    "package_version",
    "user_agent",
    "CONTACT_ENV_VAR",
    "PROJECT_URL",
    "WIKIMEDIA_FETCH_WIDTH",
    "DFLT_DEDUPE",
    "DFLT_DEDUPE_STRATEGY",
    "DFLT_N",
    "DFLT_SOURCES",
    "DFLT_LICENSE_ALLOWLIST",
    "HTTP_TIMEOUT",
    "MAX_PAGES",
    "SEARCH_CACHE_SCHEMA",
]

# --- Defaults (no magic numbers anywhere else) ------------------------------

#: Where this project lives; the contact URL in the default User-Agent.
PROJECT_URL = "https://github.com/reeleehq/illustration"

#: Environment variable holding an operator's own contact (an email or URL) for
#: the User-Agent. Wikimedia's policy asks every client for a way to reach its
#: operator, and throttles clients that give none; set this in deployments.
#: Note the User-Agent is shared, so every provider sees this contact too.
CONTACT_ENV_VAR = "ILLUSTRATION_CONTACT"

#: Width (px) of the Wikimedia thumbnail bucket used when fetching bytes for
#: real work. 1280 and 1024 are reliable buckets; 1600 answers 400 for many files.
WIKIMEDIA_FETCH_WIDTH = 1280

#: Default number of results requested *per source*.
DFLT_N = 10

#: Collapse same-subject duplicates in ``search()``. A search for one person
#: routinely returns several reproductions of the same portrait, and a consumer
#: asking for N images wants N *subjects*, not N files.
#:
#: The default is ``"auto"``, not ``True``, and the distinction is the whole
#: design: telling two engravings of one sitter apart requires *looking at the
#: pixels*, which a bare ``search()`` deliberately never does — it is a metadata
#: call with an offline contract. So dedup rides along with image work already
#: being paid for: ``"auto"`` means "dedupe when this call fetches images anyway"
#: (i.e. when reranking). Pass ``dedupe=True`` to force it and accept the
#: fetches, or ``False`` to switch it off. The curation layer, which always
#: fetches, dedupes unconditionally.
DFLT_DEDUPE = "auto"

#: What to keep from each duplicate group: the largest reproduction.
DFLT_DEDUPE_STRATEGY = "best"

#: Default source set used when ``search(..., source=None)``. Openverse first
#: because it needs no API key (works out of the box).
DFLT_SOURCES = ("openverse",)

#: Conservative default license allowlist for the (opt-in) license gate.
#: CC0 / public-domain / CC-BY / CC-BY-SA are commercial-safe (BY-SA imposes
#: share-alike — flagged, not rejected). NC/ND and unknowns are excluded.
#: Entries are compared *after* :func:`illustration.licensing.normalize_license`
#: runs over both sides, so a provider's own spelling (``cc-by-sa-4.0``,
#: ``Pixabay License``) matches the canonical code written here.
DFLT_LICENSE_ALLOWLIST = frozenset(
    {"cc0", "pdm", "by", "by-sa", "pexels-license", "pixabay-license"}
)

#: HTTP request timeout, seconds.
HTTP_TIMEOUT = 30

#: Hard safety cap on how many pages a single ``search`` will fetch, so an
#: unbounded ``n`` (or a misbehaving provider) can never loop forever.
MAX_PAGES = 25

#: Version token folded into every cache key, so a result-schema change
#: invalidates the cache *structurally* (a new key) rather than by deletion.
SEARCH_CACHE_SCHEMA = (
    "illustration.search/v2"  # v2: Wikimedia credits name the licence (#48)
)


# --- Directories ------------------------------------------------------------


def _base_dir(env_var: str, xdg_var: str, home_subpath: str) -> Path:
    """Resolve a base dir: explicit env var > XDG var > ``~`` fallback."""
    explicit = os.environ.get(env_var)
    if explicit:
        return Path(explicit).expanduser()
    xdg = os.environ.get(xdg_var)
    if xdg:
        return Path(xdg).expanduser() / "illustration"
    return Path.home() / home_subpath / "illustration"


def config_dir(*, ensure: bool = False) -> Path:
    """Directory for durable configuration (e.g. registered sources)."""
    return _ensure(
        _base_dir("ILLUSTRATION_CONFIG_DIR", "XDG_CONFIG_HOME", ".config"), ensure
    )


def data_dir(*, ensure: bool = False) -> Path:
    """Directory for durable data."""
    return _ensure(
        _base_dir("ILLUSTRATION_DATA_DIR", "XDG_DATA_HOME", ".local/share"), ensure
    )


def cache_dir(*, ensure: bool = False) -> Path:
    """Directory for regenerable caches (the default search-result store)."""
    return _ensure(
        _base_dir("ILLUSTRATION_CACHE_DIR", "XDG_CACHE_HOME", ".cache"), ensure
    )


def _ensure(path: Path, ensure: bool) -> Path:
    if ensure:
        path.mkdir(parents=True, exist_ok=True)
    return path


# --- Identity ---------------------------------------------------------------


def package_version() -> str:
    """The installed package version, or ``'0+unknown'`` if not installed.

    >>> isinstance(package_version(), str)
    True
    """
    try:
        return version("illustration")
    except PackageNotFoundError:
        return "0+unknown"


def user_agent(*, contact: "str | None" = None) -> str:
    """A policy-compliant User-Agent: ``name/version (contact) library/version``.

    That is the shape Wikimedia's User-Agent policy documents, and
    ``upload.wikimedia.org`` throttles anything vaguer, in a way that looks
    exactly like a rate limit. The contact is ``contact``, else the
    :data:`CONTACT_ENV_VAR` environment variable (an operator's own email or
    URL), else the project URL.

    >>> user_agent().startswith('illustration/')
    True
    >>> user_agent(contact='ops@example.org')       # doctest: +ELLIPSIS
    'illustration/... (https://github.com/reeleehq/illustration; ops@example.org) ...'
    """
    operator = contact or os.environ.get(CONTACT_ENV_VAR)
    # A control character (a stray newline in an env var) makes `requests`
    # refuse the header, which would fail every provider and every image fetch.
    operator = " ".join(operator.split()) if operator else operator
    contacts = "; ".join(filter(None, (PROJECT_URL, operator)))
    return f"illustration/{package_version()} ({contacts}) {_http_library_token()}"


def _http_library_token() -> str:
    """``python-requests/<version>``, the library token the policy asks for."""
    try:
        import requests

        return f"python-requests/{requests.__version__}"
    except ImportError:  # requests is lazy and optional at import time
        return "python-urllib"
