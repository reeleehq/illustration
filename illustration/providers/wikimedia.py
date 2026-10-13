"""Wikimedia Commons source — 140M+ free media, **no key**, deep file metadata.

Wikimedia Commons (the MediaWiki Action API at
``https://commons.wikimedia.org/w/api.php``) adds breadth and historical /
editorial / fine-art / scientific reference imagery to the no-key default set.
It uses a ``generator=search`` query feeding ``prop=imageinfo`` so each hit
carries the full image URL, a thumbnail, and ``extmetadata`` (license, license
URL, artist, attribution).

This adapter exercises the base's general extension hooks (no per-provider hacks
in the façade): :attr:`fixed_params` (the constant ``action=query`` / ``format``
/ ``generator`` / ``gsrnamespace`` / ``prop`` / ``iiprop`` params) and
:meth:`_page_params` (Wikimedia paginates by ``gsroffset``, not page number).

Quirks handled here: the response's ``query.pages`` is a **dict keyed by
pageid** (sorted here by the search ``index`` to preserve relevance order);
licenses **vary per file** (so pair with the ``license_allow`` gate for
commercial use); the ``Artist`` field is **HTML** (stripped for ``author``,
with the first ``href`` lifted into ``author_url``); the File namespace includes
non-images (PDF/audio/video) which are dropped during normalization by MIME.

It supports **none** of the canonical search-time filters (orientation/size/
safe/license_type/color/content_type) — they degrade gracefully.
"""

from __future__ import annotations

import unicodedata
from urllib.parse import urlsplit

import html
import re
from typing import Any, Iterable, Mapping

from illustration.base import RetrievalSource, SourceInfo
from illustration.schema import ImageResult

__all__ = ["WikimediaSource", "thumbnail_at_width"]

_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
_THUMB_WIDTH = "320"  # px width requested for the generated thumbnail URL
# What actually caps a page at 50 here is `iiurlwidth`: requesting scaled
# thumbnails limits a response to "no more than 50 scaled images". The search
# generator itself (`gsrlimit`) is documented as 1-500 with no anonymous
# distinction — so raising this cap means dropping `iiurlwidth` (and the
# thumbnail URLs it produces), not asking the search API for more.
_SCALED_IMAGE_LIMIT = 50


_UPLOAD_HOST = "upload.wikimedia.org"
# The last path segment of a thumbnail URL: `[page1-]320px-Name.jpg`.
_THUMB_SEGMENT_RE = re.compile(r"^((?:page\d+-)?)\d+(px-.+)$")


def thumbnail_at_width(
    url: "str | None", width: int, *, original_width: "int | None" = None
) -> "str | None":
    """Rewrite a Commons thumbnail URL to render at ``width`` px.

    Fetching the 15 MB original just to downscale it is the slow path, and
    ``upload.wikimedia.org`` serves arbitrary widths of any thumbnail URL. Only
    URLs already in ``/thumb/`` form on the upload host are touched (anything
    else comes back unchanged), and a ``width`` above ``original_width`` is left
    alone because the service answers 400 to an upscale.

    >>> u = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/320px-X.jpg"
    >>> thumbnail_at_width(u, 1280)
    'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/1280px-X.jpg'
    >>> thumbnail_at_width(u, 1280, original_width=900) == u
    True
    >>> thumbnail_at_width("https://example.org/a.jpg", 1280)
    'https://example.org/a.jpg'
    """
    if not url or urlsplit(url).netloc != _UPLOAD_HOST or "/thumb/" not in url:
        return url
    if original_width is not None and width > original_width:
        return url
    head, _, last = url.rpartition("/")
    m = _THUMB_SEGMENT_RE.match(last)
    return f"{head}/{m.group(1)}{width}{m.group(2)}" if m else url


_CATEGORY_PREFIX = "category:"
_FILE_PREFIX = "file:"


def _is_file_title(query: str) -> bool:
    """Whether ``query`` names one exact Commons file.

    >>> _is_file_title("File:Alexander Hamilton.jpg")
    True
    >>> _is_file_title("Alexander Hamilton")
    False
    """
    return query.strip().lower().startswith(_FILE_PREFIX)


def _is_category(query: str) -> bool:
    """Whether ``query`` names a Commons category rather than free text.

    >>> _is_category("Category:Elizabeth Schuyler Hamilton")
    True
    >>> _is_category("category:trinity church")   # MediaWiki is case-insensitive here
    True
    >>> _is_category("Elizabeth Schuyler Hamilton")
    False
    """
    return query.strip().lower().startswith(_CATEGORY_PREFIX)


def _category_title(query: str) -> str:
    """Normalise to the canonical ``Category:Name`` title.

    >>> _category_title("category:  Trinity Church (Manhattan) ")
    'Category:Trinity Church (Manhattan)'
    """
    return "Category:" + query.strip()[len(_CATEGORY_PREFIX) :].strip()


def _file_title(query: str) -> str:
    """Normalise to the canonical ``File:Name`` title.

    >>> _file_title("file:  Alexander Hamilton.jpg ")
    'File:Alexander Hamilton.jpg'
    """
    return "File:" + query.strip()[len(_FILE_PREFIX) :].strip()


def _strip_html(value: "str | None") -> "str | None":
    """Strip tags + unescape entities from an extmetadata HTML value."""
    if not value:
        return None
    text = html.unescape(_TAG_RE.sub("", value)).strip()
    return text or None


def _first_href(value: "str | None") -> "str | None":
    if not value:
        return None
    m = _HREF_RE.search(value)
    if not m:
        return None
    url = m.group(1)
    return ("https:" + url) if url.startswith("//") else url


class WikimediaSource(RetrievalSource):
    """Pure-search adapter for Wikimedia Commons (MediaWiki Action API)."""

    name = "wikimedia"
    endpoint = "https://commons.wikimedia.org/w/api.php"
    query_param = "gsrsearch"
    max_per_page = _SCALED_IMAGE_LIMIT
    api_user_agent = True  # Wikimedia asks for it, and allows it in preflights
    fixed_params = {
        "action": "query",
        "format": "json",
        # formatversion 2 returns `query.pages` as a LIST in API order. Under
        # version 1 it is a dict keyed by pageid, and a JavaScript consumer
        # loses that order at parse time (integer-like keys are re-sorted), so
        # category members — which carry no `index` — would come back in a
        # different order in the TS twin than here. A list has no such trap.
        "formatversion": "2",
        "generator": "search",
        "gsrnamespace": "6",  # the File namespace
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime|user",
        "iiurlwidth": _THUMB_WIDTH,  # produces a thumbnail URL
        # MediaWiki sends CORS headers only when the request is marked as
        # anonymous cross-origin by `origin=*`. Harmless server-side, and the
        # TS twin (a browser) reads this same record, so it needs it (#44).
        "origin": "*",
    }
    # param_map left empty: Commons exposes no canonical search-time filters here.
    info = SourceInfo(
        name="wikimedia",
        description="140M+ free media files with deep per-file metadata; no key.",
        requires_key=False,
        homepage="https://commons.wikimedia.org",
        default_cacheable=True,
        license_note="Per-file license varies (CC/PD; some share-alike) — gate for commercial use.",
        rate_limit="etiquette-bound (descriptive User-Agent required)",
        tags=("open", "historical", "editorial", "breadth", "no-key"),
    )

    def _page_params(self, *, page: int, per_page: int) -> dict:
        # offset-based pagination, not page-number based
        return {"gsrlimit": per_page, "gsroffset": (page - 1) * per_page}

    def _query_params(self, query: str, *, page: int, per_page: int) -> dict:
        """Route a ``Category:…`` query to the category-members generator.

        A Commons **category** is a curated list — maintained by people who
        looked at the pictures — where free-text search is a guess at the
        filename and description. The difference is not marginal: searching
        "Hamilton Grange" returns a branch library of that name, while
        ``Category:Hamilton Grange National Memorial`` returns the house. For a
        subject with a category, this is the better door.

        Detected from the query's own namespace prefix rather than a new
        parameter, because that is MediaWiki's own spelling for it and it
        therefore survives the façade, the cache key and the CLI unchanged.
        """
        if _is_file_title(query):
            # Exact titles, not a search. Relevance ranking cannot reliably
            # surface a *generic* filename — "File:Alexander Hamilton.jpg" is not
            # in the top hits for "Alexander Hamilton", because thousands of
            # files match that phrase better than one plainly-named one does.
            # A caller who already knows the file should not have to hope.
            # Multiple titles may be pipe-separated, as the MediaWiki API takes them.
            return {
                "generator": None,  # dropped by _get; this is a direct lookup
                "titles": "|".join(
                    _file_title(part) for part in query.split("|") if part.strip()
                ),
            }
        if not _is_category(query):
            return super()._query_params(query, page=page, per_page=per_page)
        return {
            "generator": "categorymembers",
            "gcmtitle": _category_title(query),
            "gcmtype": "file",
            # Category members have no relevance order to page through, and the
            # 50-scaled-image cap already bounds a page; ask once and stop.
            "gcmlimit": per_page,
        }

    def _items(self, response: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        pages = (response.get("query") or {}).get("pages") or []
        # A list under formatversion 2; a dict keyed by pageid under version 1
        # (still accepted, for stored responses). Sort by search `index` for
        # relevance order; category members carry no `index`, so the stable
        # sort keeps their API order.
        items = pages.values() if isinstance(pages, Mapping) else pages
        return sorted(items, key=lambda p: p.get("index", 0))

    def _normalize(self, item: Mapping[str, Any], *, query: str) -> ImageResult:
        info = (item.get("imageinfo") or [{}])[0]
        if not str(info.get("mime", "")).startswith("image/"):
            raise ValueError("not an image file")  # dropped by _safe_normalize
        em = info.get("extmetadata") or {}

        def _em(key: str) -> "str | None":
            v = em.get(key)
            return v.get("value") if isinstance(v, dict) else None

        artist_html = _em("Artist")
        title = item.get("title") or ""
        if title.startswith("File:"):
            title = title[len("File:") :]
        license_short = _em("LicenseShortName")
        return ImageResult(
            provider=self.name,
            id=str(item["pageid"]),  # KeyError -> the item is skipped, not id "None"
            url=info.get("url"),
            thumbnail_url=info.get("thumburl"),
            width=info.get("width"),
            height=info.get("height"),
            title=title or None,
            description=_strip_html(_em("ImageDescription")),
            tags=[],  # Commons categories are noisy/HTML; omitted at this layer
            license=_em("License") or license_short,
            license_url=_em("LicenseUrl"),
            attribution=_attribution(
                _strip_html(_em("Attribution")),
                _strip_html(artist_html),
                license_short or _em("License") or _em("LicenseUrl"),
                license=_em("License") or license_short,
                license_url=_em("LicenseUrl"),
            ),
            source_page_url=info.get("descriptionurl"),
            author=_strip_html(artist_html),
            author_url=_first_href(artist_html),
            cacheable=True,  # free content; preserve attribution (gate per-file license)
            avg_color=None,
            query=query,
            raw=dict(item),
        )


def _attribution(
    raw: "str | None",
    author: "str | None",
    license_short: "str | None",
    *,
    license: "str | None" = None,
    license_url: "str | None" = None,
) -> "str | None":
    """The credit sentence, always naming the licence when one is known.

    - The uploader's own ``Attribution`` wording is kept **verbatim as a
      prefix**: it is the rights-holder's stated credit.
    - When that wording does not identify the licence (by the same rule
      :func:`illustration.check_attributions` audits with,
      :func:`illustration.licensing.attribution_names_license`: "© Alice" or a
      different CC code does not count), the licence is appended: ``"Use freely, credit ACME / CC BY 4.0, via
      Wikimedia Commons"``. CC BY / BY-SA require the licence to be
      identified, so rendering the bare wording, as the documented contract
      says to, would breach it (illustration#48, decided 2026-10-12).
    - An ``Attribution`` that is just the ``Artist`` name again
      (illustration#22) is replaced by the composed author + licence credit.
    - With no licence known, the wording is returned as it is: there is
      nothing to append.
    """
    from illustration.licensing import attribution_names_license

    if not raw or (author and _same_text(raw, author)):
        return _build_attribution(author, license_short)
    if not license_short or attribution_names_license(
        raw, license or license_short, license_url=license_url
    ):
        return raw
    stem = _VIA_COMMONS_RE.sub("", raw).rstrip(" ,;/\u2014\u2013-")
    return f"{stem} / {license_short}, via Wikimedia Commons"


_VIA_COMMONS_RE = re.compile(
    r"[\s,;/\u2014\u2013-]*\bvia\s+wikimedia(?:\s+commons)?[\s.,;]*$", re.I
)


def _same_text(a: str, b: str) -> bool:
    """Equal once case and surrounding whitespace/punctuation are ignored."""

    def norm(x: str) -> str:
        x = unicodedata.normalize("NFC", x)
        return " ".join(x.split()).strip(" .,;").casefold()

    return norm(a) == norm(b)


def _build_attribution(
    author: "str | None", license_short: "str | None"
) -> "str | None":
    if author and license_short:
        return f"{author} / {license_short}, via Wikimedia Commons"
    if author:
        return f"{author}, via Wikimedia Commons"
    if license_short:
        return f"{license_short}, via Wikimedia Commons"
    return None
