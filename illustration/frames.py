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
  ``embed_pil_images(images)`` fits (an ONNX text encoder on a machine
  without torch, for instance).
- ``store``: where the corpus lives, one entry per video (its times, its
  vectors, its title and licence). Default: JSON files under the cache dir, per
  model, since a corpus is regenerable.

**Limits to know.** A storyboard frame stands for a few seconds and can lag
the moment it shows by about a second, so cut the real frame from a few
candidate times around a hit (``yb.download``'s ``start``/``end``). At 320x180
it finds scenes, not small props; a caption track can find what the picture
cannot (search both).

**Licence.** A hit carries its video's licence. A YouTube video that is not
under YouTube's Creative Commons licence is all rights reserved: fine to find
and study, not to republish. ``FrameHit.license`` says which.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, MutableMapping, Sequence

from illustration.config import cache_dir

__all__ = [
    "FrameHit",
    "index_video_frames",
    "search_frames",
    "storyboard_sampler",
    "default_frame_store",
    "frame_license",
    "DFLT_PER_VIDEO",
    "DFLT_MIN_GAP_S",
]

#: At most this many hits from one video, so one long video cannot fill the list.
DFLT_PER_VIDEO = 3
#: Two hits in one video closer than this (seconds) are one scene: keep the best.
DFLT_MIN_GAP_S = 12.0
#: Frames embedded per forward pass.
DFLT_BATCH = 64

#: YouTube's own name for its Creative Commons licence (yt-dlp's ``license``).
_YOUTUBE_CC = "creative commons"


def frame_license(raw: str | None) -> str:
    """A video licence as one canonical code: ``CC-BY`` for YouTube's Creative
    Commons licence, else ``all-rights-reserved`` (YouTube's standard licence,
    or no licence stated).

    >>> frame_license("Creative Commons Attribution license (reuse allowed)")
    'CC-BY'
    >>> frame_license(None), frame_license("Standard YouTube License")
    ('all-rights-reserved', 'all-rights-reserved')
    """
    return "CC-BY" if raw and _YOUTUBE_CC in raw.lower() else "all-rights-reserved"


@dataclass(frozen=True)
class FrameHit:
    """One frame that matches a query: which video, when, how well, under what licence."""

    video_id: str
    video_url: str
    t: float
    score: float
    title: str | None = None
    license: str = "all-rights-reserved"
    license_raw: str | None = None

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
    """A video's YouTube storyboard (``yb.download.youtube_storyboard``)."""
    try:
        from yb.download import youtube_storyboard
    except ImportError as error:  # pragma: no cover - the message is the point
        raise ImportError(
            "the storyboard sampler reads YouTube through yb: install the "
            "[frames] extra, or pass sampler="
        ) from error
    return youtube_storyboard(url, **kwargs)


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


def _entry_key(video_id: str) -> str:
    from illustration.reranking import _slug

    return f"{_slug(video_id)}.json"


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

    A video already in the store is skipped unless ``refresh=True``, so
    indexing a channel again only does the new videos. A video the sampler
    cannot read (no storyboard, unavailable, a network error) is recorded in
    ``failed`` with the reason and the others go on.

    Returns:
        ``{"indexed": [video ids], "skipped": [video ids], "failed": {url: why},
        "frames": number of frames embedded}``.
    """
    model = _model_name(model)
    store = default_frame_store(model) if store is None else store
    report: dict = {"indexed": [], "skipped": [], "failed": {}, "frames": 0}
    for url in videos:
        try:
            video = sampler(url)
        except Exception as error:  # noqa: BLE001 - one unreadable video is a note
            report["failed"][url] = f"{type(error).__name__}: {error}"
            continue
        key = _entry_key(video.video_id or url)
        if not refresh and key in store:
            report["skipped"].append(video.video_id)
            continue
        times, images = [], []
        for t, image in video.frames():
            times.append(float(t))
            images.append(image)
        if scorer is None:
            scorer = _default_scorer(model)
        vectors = scorer.embed_pil_images(images, batch=batch) if images else []
        store[key] = {
            "video_id": video.video_id,
            "url": video.url,
            "title": video.title,
            "duration": video.duration,
            "license": video.license,
            "model": model,
            "times": times,
            "vectors": [[float(x) for x in v] for v in vectors],
        }
        report["indexed"].append(video.video_id)
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
    search to those video ids.
    """
    import numpy as np

    model = _model_name(model)
    store = default_frame_store(model) if store is None else store
    scorer = _default_scorer(model) if scorer is None else scorer
    query = np.asarray(scorer.embed_text(text), dtype="float32")
    wanted = None if videos is None else set(videos)
    scored: list[tuple[float, float, dict]] = []
    for key in store:
        entry = store[key]
        if wanted is not None and entry["video_id"] not in wanted:
            continue
        if not entry["vectors"]:
            continue
        sims = np.asarray(entry["vectors"], dtype="float32") @ query
        scored.extend(
            (float(s), float(t), entry) for s, t in zip(sims, entry["times"])
        )
    scored.sort(key=lambda row: -row[0])
    picked: list[FrameHit] = []
    count: dict[str, int] = {}
    for score, t, entry in scored:
        vid = entry["video_id"]
        if count.get(vid, 0) >= per_video:
            continue
        if any(h.video_id == vid and abs(h.t - t) < min_gap_s for h in picked):
            continue
        picked.append(
            FrameHit(
                video_id=vid,
                video_url=entry["url"],
                t=t,
                score=score if math.isfinite(score) else -1.0,
                title=entry.get("title"),
                license=frame_license(entry.get("license")),
                license_raw=entry.get("license"),
            )
        )
        count[vid] = count.get(vid, 0) + 1
        if len(picked) >= k:
            break
    return picked
