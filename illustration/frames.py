"""Text-to-frame search over a video corpus: find *where* in a set of videos something is.

"A cartoon wall clock", "a bedroom at night", "Tokyo Tower": instead of
scrubbing, index the videos' frames once with SigLIP, then ask in words. One
more illustration source, where an "image" is ``(video, t)`` (#46).

    >>> from illustration.frames import index_video_frames, search_frames  # doctest: +SKIP
    >>> index_video_frames(["https://youtu.be/<id>", ...])  # doctest: +SKIP
    >>> for hit in search_frames("a cartoon wall clock", k=12):  # doctest: +SKIP
    ...     print(hit.watch_url, round(hit.score, 3), hit.license)

**Three seams, with working defaults.**

- ``sampler``: a video URL to its frames. The default,
  :func:`storyboard_sampler`, reads YouTube's storyboard (the seek-bar
  thumbnails, 320x180, one every few seconds) through
  ``yb.download.youtube_storyboard``: no video download, and it works where
  video downloads hit a bot wall. Anything returning an object with
  ``video_id``, ``url``, ``title``, ``duration``, ``license`` and ``frames()``
  (``(t, PIL image)`` pairs) fits, e.g. frames sampled from a local file.
- ``scorer``: what embeds the frames and the query. The default is the
  package's SigLIP 2 scorer (:class:`illustration.reranking.SiglipScorer`,
  the ``[rerank]`` extra); anything with ``embed_text(text)`` and
  ``embed_pil_images(images, *, batch)`` fits (an ONNX text encoder on a
  machine without torch, for instance), and its ``model_id`` (if it has one)
  is recorded with the corpus: a search with another model skips those videos
  and warns, since their vectors are not comparable.
- ``store``: where the corpus lives, one entry per video (its times, its
  vectors, its title and licence). Default: JSON files under the cache dir, per
  model, since a corpus is regenerable.

**Limits to know.** A storyboard frame stands for a few seconds and can lag
the moment it shows by about a second, so cut the real frame from a few
candidate times around a hit (``yb.download``'s ``start``/``end``). At 320x180
it finds scenes, not small props; a caption track can find what the picture
cannot (search both).

**Licence.** A hit carries the package's full rights record
(:data:`illustration.schema.RIGHTS_FIELDS`): the licence as the canonical
code of :func:`illustration.licensing.normalize_license` (YouTube's Creative
Commons licence is ``by``; its standard licence, which is all rights reserved,
is ``youtube-standard-license``; ``None`` when the sampler did not say), the
licence URL, an attribution line, the author and their page, the source page
(the video at that moment), and ``cacheable=False`` (the frames are never
stored, only their embeddings). Fine to find and study; republishing follows
the licence.
"""

from __future__ import annotations

import hashlib
import math
import re
import warnings
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable, MutableMapping, Sequence

from illustration.config import cache_dir

__all__ = [
    "FrameHit",
    "index_video_frames",
    "search_frames",
    "storyboard_sampler",
    "default_frame_store",
    "frame_license",
    "youtube_video_id",
    "DFLT_PER_VIDEO",
    "DFLT_MIN_GAP_S",
]

#: At most this many hits from one video, so one long video cannot fill the list.
DFLT_PER_VIDEO = 3
#: Two hits in one video closer than this (seconds) are one scene: keep the best.
DFLT_MIN_GAP_S = 12.0
#: Frames embedded per forward pass.
DFLT_BATCH = 64

#: YouTube's standard licence, under which every video not marked Creative
#: Commons is published (yt-dlp reports no ``license`` for it).
YOUTUBE_STANDARD_LICENSE = "YouTube Standard License"

#: Where each licence's terms are, by canonical code. YouTube's Creative Commons
#: option is CC BY 3.0.
_LICENSE_URLS = {
    "by": "https://creativecommons.org/licenses/by/3.0/",
    "youtube-standard-license": "https://www.youtube.com/t/terms",
}


def frame_license(raw: str | None) -> str | None:
    """A video licence as the package's canonical code
    (:func:`illustration.licensing.normalize_license`); ``None`` when unknown.

    >>> frame_license("Creative Commons Attribution license (reuse allowed)")
    'by'
    >>> frame_license(YOUTUBE_STANDARD_LICENSE), frame_license(None)
    ('youtube-standard-license', None)
    >>> frame_license("CC BY-NC 4.0")  # a custom sampler's licence keeps its NC
    'by-nc'
    """
    from illustration.licensing import normalize_license

    return normalize_license(raw)


def youtube_video_id(url: str) -> str | None:
    """The video id in a YouTube URL, or ``None``: lets indexing skip a video it
    already has without fetching anything.

    >>> youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3")
    'dQw4w9WgXcQ'
    >>> youtube_video_id("https://youtu.be/a-b_cdefghi"), youtube_video_id("/films/a.mp4")
    ('a-b_cdefghi', None)
    """
    found = re.search(
        r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|shorts/|embed/|live/)|youtu\.be/)"
        r"([A-Za-z0-9_-]{6,})",
        url or "",
    )
    return found.group(1) if found else None


@dataclass(frozen=True)
class FrameHit:
    """One frame that matches a query: which video, when, how well, and the
    rights record (:data:`illustration.schema.RIGHTS_FIELDS`) of that video."""

    video_id: str
    video_url: str
    t: float
    score: float
    title: str | None = None
    license: str | None = None  # canonical code; None: the sampler did not say
    license_raw: str | None = None
    license_url: str | None = None
    attribution: str | None = None
    author: str | None = None
    author_url: str | None = None
    cacheable: bool = False  # only embeddings are kept, never the frames

    @property
    def source_page_url(self) -> str:
        """The page the frame is on: the video at this moment (:attr:`watch_url`)."""
        return self.watch_url

    @property
    def rights(self) -> dict:
        """The rights record, by :data:`illustration.schema.RIGHTS_FIELDS`' names."""
        from illustration.schema import RIGHTS_FIELDS

        return {name: getattr(self, name) for name in RIGHTS_FIELDS}

    @property
    def watch_url(self) -> str:
        """The video URL opening at this frame (whole seconds).

        >>> FrameHit("v", "https://www.youtube.com/watch?v=v", 75.4, 0.2).watch_url
        'https://www.youtube.com/watch?v=v&t=75s'
        >>> FrameHit("v", "https://youtu.be/v", 9.0, 0.2).watch_url
        'https://youtu.be/v?t=9s'
        """
        sep = "&" if "?" in self.video_url else "?"
        return f"{self.video_url}{sep}t={int(self.t)}s"


def storyboard_sampler(url: str, **kwargs) -> Any:
    """A video's YouTube storyboard (``yb.download.youtube_storyboard``).

    A YouTube video with no licence reported is under YouTube's standard
    licence, so that is what it records (:data:`YOUTUBE_STANDARD_LICENSE`).
    """
    try:
        from yb.download import youtube_storyboard
    except ImportError as error:  # pragma: no cover - the message is the point
        raise ImportError(
            "the storyboard sampler reads YouTube through yb: install the "
            "[frames] extra, or pass sampler="
        ) from error
    board = youtube_storyboard(url, **kwargs)
    return board if board.license else replace(board, license=YOUTUBE_STANDARD_LICENSE)


def default_frame_store(model: str) -> "MutableMapping[str, Any]":
    """JSON files under the cache dir, one per video, per embedding model."""
    from dol import JsonFiles

    from illustration.reranking import _slug

    root = cache_dir(ensure=True) / "frames" / _slug(model)
    root.mkdir(parents=True, exist_ok=True)
    return JsonFiles(str(root))


def _default_scorer(model: str):
    from illustration.reranking import make_siglip_scorer

    return make_siglip_scorer(model=model)


def _model_name(model: str | None) -> str:
    if model is not None:
        return model
    from illustration.reranking import DFLT_RERANK_MODEL

    return DFLT_RERANK_MODEL


def _entry_key(identity: str) -> str:
    """One store key per video: a digest of its identity, so ids differing only
    in ``-``/``_``, case or path separators never share an entry."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40] + ".json"


def _attribution(title, author, license_code, license_raw) -> str | None:
    from illustration.licensing import display_license

    what = f'"{title}"' if title else "Video"
    by = f" by {author}" if author else ""
    terms = display_license(license_code) or license_raw
    return f"{what}{by}" + (f", {terms}" if terms else "")


def index_video_frames(
    videos: Iterable[str],
    *,
    store: "MutableMapping[str, Any] | None" = None,
    sampler: Callable[[str], Any] = storyboard_sampler,
    scorer: Any = None,
    model: str | None = None,
    refresh: bool = False,
    batch: int = DFLT_BATCH,
) -> dict:
    """Embed every frame of ``videos`` into the corpus; return what happened.

    A video already in the store is skipped unless ``refresh=True`` (for a
    YouTube URL, without fetching anything), so indexing a channel again only
    does the new videos. A video that cannot be read or embedded (no
    storyboard, unavailable, a corrupt sheet, a scorer error) is recorded in
    ``failed`` with the reason, nothing is written for it, and the others go
    on. Frames are embedded ``batch`` at a time as they are read, so a long
    video never sits in memory whole.

    Returns:
        ``{"indexed": [ids], "skipped": [ids], "failed": {url: why},
        "frames": number of frames embedded}``; a video's id is its
        ``video_id``, else its URL.
    """
    model = _model_name(model)
    store = default_frame_store(model) if store is None else store
    report: dict = {"indexed": [], "skipped": [], "failed": {}, "frames": 0}
    for url in videos:
        known = youtube_video_id(url)
        if known and not refresh and _entry_key(known) in store:
            report["skipped"].append(known)
            continue
        try:
            video = sampler(url)
            identity = video.video_id or video.url or url
            key = _entry_key(identity)
            if not refresh and key in store:
                report["skipped"].append(identity)
                continue
            if scorer is None:
                scorer = _default_scorer(model)
            times, vectors, pending = [], [], []

            def flush():
                vectors.extend(scorer.embed_pil_images(pending, batch=batch))
                pending.clear()

            for t, image in video.frames():
                times.append(float(t))
                pending.append(image)
                if len(pending) >= batch:
                    flush()
            if pending:
                flush()
        except Exception as error:  # noqa: BLE001 - one bad video is a note, not the end
            report["failed"][url] = f"{type(error).__name__}: {error}"
            continue
        store[key] = {
            "id": identity,
            "video_id": video.video_id,
            "url": video.url or url,
            "title": video.title,
            "duration": video.duration,
            "license": video.license,
            "author": getattr(video, "uploader", None) or getattr(video, "channel", None),
            "author_url": getattr(video, "channel_url", None),
            "model": getattr(scorer, "model_id", None) or model,
            "times": times,
            "vectors": [[float(x) for x in v] for v in vectors],
        }
        report["indexed"].append(identity)
        report["frames"] += len(times)
    return report


def search_frames(
    text: str,
    *,
    store: "MutableMapping[str, Any] | None" = None,
    scorer: Any = None,
    model: str | None = None,
    k: int = 10,
    per_video: int = DFLT_PER_VIDEO,
    min_gap_s: float = DFLT_MIN_GAP_S,
    videos: Sequence[str] | None = None,
) -> list[FrameHit]:
    """The ``k`` frames that best match ``text``, best first.

    Diversified, because the next frame of a match is usually a match too: at
    most ``per_video`` hits per video, and two hits closer than ``min_gap_s``
    in one video are one scene (the better one is kept). ``videos`` limits the
    search to those video ids (or URLs, for a video that has no id). Videos
    indexed with another embedding model are skipped, with a warning.
    """
    import numpy as np

    model = _model_name(model)
    store = default_frame_store(model) if store is None else store
    scorer = _default_scorer(model) if scorer is None else scorer
    using = getattr(scorer, "model_id", None) or model
    query = np.asarray(scorer.embed_text(text), dtype="float32")
    wanted = None if videos is None else set(videos)
    scored: list[tuple[float, float, dict]] = []
    other_model: list[str] = []
    for key in store:
        entry = store[key]
        identity = entry.get("id") or entry["video_id"] or entry["url"]
        if wanted is not None and identity not in wanted:
            continue
        if not entry["vectors"]:
            continue
        if entry.get("model", using) != using:
            other_model.append(identity)
            continue
        sims = np.asarray(entry["vectors"], dtype="float32") @ query
        scored.extend(
            (float(s), float(t), entry) for s, t in zip(sims, entry["times"])
        )
    if other_model:
        warnings.warn(
            f"search_frames: skipped {len(other_model)} video(s) indexed with another "
            f"model than {using!r} (their vectors are not comparable): "
            f"{sorted(other_model)[:5]}; re-index them with refresh=True",
            stacklevel=2,
        )
    scored.sort(key=lambda row: -row[0])
    picked: list[FrameHit] = []
    count: dict[str, int] = {}
    seen: list[tuple[str, float]] = []
    for score, t, entry in scored:
        vid = entry.get("id") or entry["video_id"] or entry["url"]
        if count.get(vid, 0) >= per_video:
            continue
        if any(v == vid and abs(pt - t) < min_gap_s for v, pt in seen):
            continue
        code = frame_license(entry.get("license"))
        picked.append(
            FrameHit(
                video_id=entry["video_id"] or vid,
                video_url=entry["url"],
                t=t,
                score=score if math.isfinite(score) else -1.0,
                title=entry.get("title"),
                license=code,
                license_raw=entry.get("license"),
                license_url=_LICENSE_URLS.get(code or ""),
                attribution=_attribution(
                    entry.get("title"), entry.get("author"), code, entry.get("license")
                ),
                author=entry.get("author"),
                author_url=entry.get("author_url"),
            )
        )
        seen.append((vid, t))
        count[vid] = count.get(vid, 0) + 1
        if len(picked) >= k:
            break
    return picked
