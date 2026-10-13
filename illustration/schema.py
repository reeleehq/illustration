"""The normalized result schema — the single source of truth (Pydantic v2).

:class:`ImageResult` is the stable contract that every provider normalizes into
and that the (future) agentic curation layer consumes. License, attribution,
``source_page_url`` and ``cacheable`` are first-class and populated from day one,
because licensing/cacheability is a primary concern for commercial-adjacent
video (see ``misc/docs/design/illustration_design.md`` §3).

>>> r = ImageResult(provider="openverse", id="abc", url="https://x/img.jpg",
...                  license="by-sa", cacheable=True)
>>> r.provider, r.cacheable, r.tags
('openverse', True, [])
>>> r.model_dump()["license"]
'by-sa'

The ``raw`` field carries the untranslated provider payload (the escape-hatch
"nothing is lost" convention), so a downstream consumer can always reach a
provider-specific field the normalized schema doesn't name.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterable, Literal, Mapping, Union

from pydantic import BaseModel, Discriminator, Field, Tag, TypeAdapter

from illustration.config import DFLT_LICENSE_ALLOWLIST
from illustration.licensing import (
    attribution_names_license,
    licenses_named,
    mentions_license,
    normalize_license,
)

__all__ = [
    "MediaResult",
    "ImageResult",
    "VideoResult",
    "Rendition",
    "TimeSpan",
    "AnyMediaResult",
    "parse_media_result",
    "require_image",
    "MEDIA_TYPES",
    "VIDEO_RIGHTS_FIELDS",
    "MEDIA_RIGHTS_FIELDS",
    "license_allowlist",
    "check_attributions",
    "to_search_hit",
    "RIGHTS_FIELDS",
]

#: The **rights record**: the fields that answer "may we ship this, and whom
#: must we credit?". This tuple is the SSOT for that question — anything that
#: persists, forwards or re-materialises an :class:`ImageResult` copies exactly
#: these, by these names, so no rename table is ever needed downstream. It is
#: the one field set that cannot be reconstructed later: a dead URL, a
#: re-keyed provider or a re-tagged aggregator all leave a stored selection
#: unable to answer it.
RIGHTS_FIELDS = (
    "license",
    "license_url",
    "attribution",
    "source_page_url",
    "author",
    "author_url",
    "cacheable",
)


#: The extra rights flags a **video** hit carries (stock footage is licensed
#: with restrictions a photo rarely has). They answer the same question as
#: :data:`RIGHTS_FIELDS` and are persisted under the same names, but they live
#: beside it rather than inside it: :data:`RIGHTS_FIELDS` is what an *image*
#: has, and it is projected wholesale onto ``walkthru.AssetRights`` and read off
#: every :class:`ImageResult`. All four are optional; ``None`` means *not
#: recorded*, which is not the same claim as ``False``.
VIDEO_RIGHTS_FIELDS = (
    "editorial_only",
    "has_model_release",
    "has_property_release",
    "audio_policy",
)

#: Everything that answers "may we ship this?" for *any* media type — what
#: persistence stores. For an image the last four are simply never recorded.
MEDIA_RIGHTS_FIELDS = RIGHTS_FIELDS + VIDEO_RIGHTS_FIELDS

#: The values of the ``media_type`` tag, in union order.
MEDIA_TYPES = ("image", "video")


class MediaResult(BaseModel):
    """What every normalized hit from any provider carries, whatever the media.

    A base, not a result: instantiate :class:`ImageResult` or
    :class:`VideoResult`. Neither subclasses the other, on purpose — code typed
    on images (the ``burns`` render hook, ``sequence``'s pHash dedupe) must not
    silently accept a video; see :func:`require_image`.

    ``media_type`` tells them apart: ``"image"`` or ``"video"``. It is a real
    serialized field on :class:`VideoResult` only. :class:`ImageResult` reports
    ``"image"`` through a read-only property and does not serialize it, so the
    image contract (dumps, JSON Schema, stored selections, parity fixtures) is
    byte-for-byte what it was; a payload with no tag *is* an image
    (:func:`parse_media_result`).
    """

    provider: str = Field(description="Source/provider name, e.g. 'openverse'.")
    id: str = Field(description="Provider-native identifier.")
    url: str = Field(description="Full-resolution image URL.")
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    title: str | None = None
    description: str | None = Field(
        default=None, description="Alt text / longer description."
    )
    tags: list[str] = Field(default_factory=list, json_schema_extra={"default": []})
    license: str | None = Field(
        default=None, description="License code or name (e.g. 'by-sa')."
    )
    license_url: str | None = None
    attribution: str | None = Field(
        default=None, description="Ready-to-render attribution sentence."
    )
    source_page_url: str | None = None
    author: str | None = None
    author_url: str | None = None
    cacheable: bool = Field(
        default=False, description="May the bytes be downloaded/cached to our server?"
    )
    avg_color: str | None = Field(
        default=None, description="Dominant-color hint where available."
    )
    # provenance / forward-compatibility
    query: str | None = Field(
        default=None, description="Canonical query that produced this hit."
    )
    score: float | None = Field(
        default=None, description="Reserved for Layer-2 rerank; None at Layer 1."
    )
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Untranslated provider payload.",
        # A default_factory emits no JSON-Schema default; the TS twin needs one
        # so a parsed result carries `{}` (and `[]` for tags) like this side does.
        json_schema_extra={"default": {}},
    )

    def to_search_hit(self):
        """Adapt to an ``ir.SearchHit`` for Layer-2 cross-provider fusion.

        Imported lazily so ``import illustration`` never requires ``ir``.
        """
        return to_search_hit(self)


class ImageResult(MediaResult):
    """One normalized image hit from any provider.

    The first eight fields plus ``cacheable`` are the cross-provider minimum the
    design guarantees; the rest are populated when a provider supplies them.
    """

    @property
    def media_type(self) -> Literal["image"]:
        """Always ``"image"``; deliberately not a serialized field (see :class:`MediaResult`)."""
        return "image"


class Rendition(BaseModel):
    """One playable encoding of a video, as a provider offers it."""

    url: str
    mime_type: str | None = None
    video_codec: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    size_bytes: int | None = None
    quality_label: str | None = Field(
        default=None, description="The provider's own label, e.g. 'hd' or '4k'."
    )
    expires_at: str | None = Field(
        default=None, description="ISO-8601 expiry of a signed URL, when it has one."
    )


class TimeSpan(BaseModel):
    """A span of a media file, in seconds.

    Maps onto an OTIO ``TimeRange``, a schema.org ``Clip`` and a media-fragment
    ``#t=start,end``.
    """

    start: float
    end: float


class VideoResult(MediaResult):
    """One normalized video hit from any provider.

    Carries the :class:`MediaResult` fields plus what is specific to footage.
    ``url`` stays the best *progressive* rendition at search time, so a reader
    of ``.url`` keeps working; ``renditions`` lists every encoding on offer.

    The four :data:`VIDEO_RIGHTS_FIELDS` are optional; ``None`` means *not
    recorded*.
    """

    media_type: Literal["video"] = "video"
    url: str = Field(description="The best progressive rendition at search time.")
    duration_s: float | None = None
    fps: float | None = None
    has_audio: bool | None = None
    renditions: list[Rendition] = Field(
        default_factory=list, json_schema_extra={"default": []}
    )
    poster_url: str | None = None
    preview_frames: list[str] = Field(
        default_factory=list, json_schema_extra={"default": []}
    )
    moment: TimeSpan | None = Field(
        default=None, description="The span that matched the query, when the provider says."
    )
    # --- video rights record (VIDEO_RIGHTS_FIELDS) ---
    editorial_only: bool | None = Field(
        default=None, description="Editorial use only (no commercial/advertising use)."
    )
    has_model_release: bool | None = None
    has_property_release: bool | None = None
    audio_policy: str | None = Field(
        default=None, description="What the soundtrack may be used for, as the provider words it."
    )


def _media_type_of(value: Any) -> str:
    """The union's callable discriminator: the tag, or ``"image"`` when absent."""
    tag = value.get("media_type") if isinstance(value, Mapping) else getattr(value, "media_type", None)
    return tag or "image"


#: Either kind of hit. Discriminated by ``media_type``; a payload without the
#: tag is an image, so every stored selection and cached result still loads.
AnyMediaResult = Annotated[
    Union[
        Annotated[ImageResult, Tag("image")],
        Annotated[VideoResult, Tag("video")],
    ],
    Discriminator(_media_type_of),
]

_MEDIA_ADAPTER = TypeAdapter(AnyMediaResult)


def parse_media_result(obj: Any) -> "ImageResult | VideoResult":
    """Validate a dict (or pass through a model) into the right result type.

    >>> parse_media_result({"provider": "p", "id": "1", "url": "u"}).media_type
    'image'
    >>> parse_media_result({"provider": "p", "id": "1", "url": "u", "media_type": "video"}).media_type
    'video'
    """
    return _MEDIA_ADAPTER.validate_python(obj)


def require_image(obj: Any, *, where: str = "this function") -> "ImageResult":
    """Return ``obj`` if it is an :class:`ImageResult`, else raise ``TypeError``.

    The guard for image-only code paths. A :class:`VideoResult` is not an
    :class:`ImageResult` by design, but duck-typed code that reads ``.url`` would
    take one without complaint and fetch a movie as a picture; this makes that
    loud.

    >>> require_image(VideoResult(provider="p", id="1", url="u"), where="render")
    Traceback (most recent call last):
    ...
    TypeError: render expects an ImageResult, got VideoResult
    """
    if not isinstance(obj, ImageResult):
        raise TypeError(f"{where} expects an ImageResult, got {type(obj).__name__}")
    return obj



def to_search_hit(result: "MediaResult"):
    """Map an :class:`ImageResult` to an ``ir.SearchHit`` for Layer-2 fusion.

    The bridge into the ``ir`` retrieval substrate so the agentic layer can
    ``ir.fuse_hits`` across providers. ``ir`` is imported here, not at module
    top, to keep the base façade dependency-light. Identity follows ir's
    ``(source, artifact_id)`` keying: ``source`` is the provider and
    ``artifact_id`` is the provider-native id. The image URL is placed under the
    ``path`` metadata key so ``SearchHit.pointer`` (which scans
    ``ir.base.POINTER_KEYS``) resolves to it; the full normalized result rides
    along in ``metadata`` too.

    ``score`` is ``0.0`` for any hit not yet reranked (Layer 1 leaves
    ``ImageResult.score`` as ``None``) — rely on *rank*, not magnitude, until a
    Layer-2 reranker populates it; ``ir.fuse_hits`` (RRF) is rank-based, so this
    is correct for fusion.
    """
    from ir import SearchHit  # lazy: Layer-2 dependency only

    return SearchHit(
        artifact_id=result.id,
        surface_kind=getattr(result, "media_type", "image"),
        score=result.score if result.score is not None else 0.0,
        text=result.description or result.title or "",
        metadata={**result.model_dump(), "path": result.url},
        source=result.provider,
    )


def license_allowlist(
    results: Iterable["MediaResult"],
    *,
    allow: "Iterable[str] | None" = None,
) -> list["MediaResult"]:
    """Keep only results whose license is on the allowlist (R3's license gate).

    The mandatory per-file license-verification gate for commercial-adjacent
    use: aggregators disclaim license accuracy, so callers should gate on a
    known-good set. Both sides are run through
    :func:`illustration.licensing.normalize_license` first, so a provider's own
    spelling (``cc-by-sa-4.0`` from Commons, ``Pixabay License``) matches the
    canonical code without the allowlist having to enumerate every dialect —
    and without ever dropping an ``nc``/``nd`` restriction. Results with no
    ``license`` are dropped (unknown == not allowed).

    >>> a = ImageResult(provider="p", id="1", url="u", license="cc0")
    >>> b = ImageResult(provider="p", id="2", url="u", license="by-nc")
    >>> c = ImageResult(provider="p", id="3", url="u", license=None)
    >>> [r.id for r in license_allowlist([a, b, c])]
    ['1']
    >>> [r.id for r in license_allowlist([a, b, c], allow={"by-nc"})]
    ['2']

    Provider dialects pass the same gate:

    >>> w = ImageResult(provider="wikimedia", id="4", url="u", license="cc-by-sa-4.0")
    >>> p = ImageResult(provider="pixabay", id="5", url="u", license="Pixabay License")
    >>> nd = ImageResult(provider="wikimedia", id="6", url="u", license="cc-by-nd-4.0")
    >>> [r.id for r in license_allowlist([w, p, nd])]
    ['4', '5']
    """
    allowed = {
        normalize_license(s)
        for s in (allow if allow is not None else DFLT_LICENSE_ALLOWLIST)
    }
    allowed.discard(None)
    return [r for r in results if normalize_license(r.license) in allowed]


def check_attributions(results: Iterable["MediaResult"]) -> list["MediaResult"]:
    """Return the results whose ``attribution`` does not visibly name a licence.

    ``license_allowlist`` gates on the *machine-readable* ``license`` field;
    this is the companion audit for the *human-readable* ``attribution``
    string a credit roll actually renders. CC BY / CC BY-SA require the
    licence to be identified in the credit — a licensed result with a
    populated, correct ``license`` can still carry an ``attribution`` that is
    just an author's name (illustration#22, seen on ~4% of one Wikimedia
    session's hits), which silently breaches that condition if a consumer
    renders ``attribution`` verbatim, as the package's own guide tells them
    to. This never rewrites or drops a result — it is read-only, for a
    pipeline to review, log, or compose a fallback credit from ``author`` /
    ``license`` / ``license_url`` for exactly the results it returns.

    What counts as "naming the licence" depends on the licence. For the
    CC BY family (``by``, ``by-sa``, ``by-nc``, ...) the attribution must name
    *that* licence (see :func:`illustration.licensing.licenses_named`), or
    contain the result's ``license_url``: "© Jane Doe", "Public domain", or a
    different CC code (e.g. "CC BY" for a ``by-nc`` image, which drops the NC
    restriction) are all flagged. For any other licence, the looser
    :func:`illustration.licensing.mentions_license` signal is used.

    A result with no ``license`` at all is not flagged: there is nothing to
    name, and it should already have been dropped by ``license_allowlist`` if
    that matters to the caller.

    >>> a = ImageResult(provider="p", id="1", url="u", license="by-sa", attribution="Jane Doe")
    >>> b = ImageResult(provider="p", id="2", url="u", license="by-sa",
    ...                  attribution="Jane Doe / CC BY-SA 4.0, via Wikimedia Commons")
    >>> c = ImageResult(provider="p", id="3", url="u", license=None, attribution=None)
    >>> [r.id for r in check_attributions([a, b, c])]
    ['1']
    """

    return [
        r
        for r in results
        if r.license
        and not attribution_names_license(
            r.attribution, r.license, license_url=r.license_url
        )
    ]


def _coerce_results(items: Iterable[Mapping[str, Any]]) -> list[ImageResult]:
    """Validate a sequence of dicts back into :class:`ImageResult` (cache reads)."""
    return [ImageResult.model_validate(d) for d in items]
