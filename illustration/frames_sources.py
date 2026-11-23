"""More ways into the frame corpus: frames from a local file, and a video's captions (#59).

Both fit the seams :mod:`illustration.frames` already has, so nothing there changes.

- :func:`file_sampler`: an every-N-seconds sampler for a local video, a ``sampler=``
  for :func:`illustration.frames.index_video_frames`. Its identity is the file's
  absolute path (the same keying as any id-less video since #56). Needs ``ffmpeg``
  on the ``PATH`` and the ``[frames]`` extra's pillow.
- :func:`search_captions`: search a video's subtitle cues beside its frames and get
  back the same :class:`~illustration.frames.FrameHit`, whose ``t`` is the cue's
  start. A caption finds what a 320x180 storyboard frame cannot (a held mug that
  is only mentioned). Scoring is lexical, on purpose: SigLIP embeds pictures and
  short captions, not a sentence of speech. The cue source is a seam
  (``loader=``), by default :func:`youtube_caption_loader` (``yb``).

    >>> parse_cues("WEBVTT\\n\\n00:00:01.000 --> 00:00:03.500\\nhello <c>there</c>\\n")
    [(1.0, 'hello there')]
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

from illustration.frames import (
    DFLT_MIN_GAP_S,
    DFLT_PER_VIDEO,
    YOUTUBE_STANDARD_LICENSE,
    FrameHit,
    _attribution,
    frame_license,
)

__all__ = [
    "file_sampler",
    "parse_cues",
    "search_captions",
    "youtube_caption_loader",
    "DFLT_EVERY_S",
]

#: Seconds between sampled frames of a local video.
DFLT_EVERY_S = 5.0

_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _seconds(stamp: str) -> float:
    h, m, s, ms = _TIME.fullmatch(stamp.strip()).groups()
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_cues(text: str) -> list[tuple[float, str]]:
    """``(start seconds, text)`` per cue of a WebVTT or SRT file, markup removed.

    Auto-generated captions repeat each line as it grows; a cue whose text equals
    the previous one is dropped.
    """
    cues: list[tuple[float, str]] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [l for l in block.strip().split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                start = line.split("-->")[0]
                if not _TIME.fullmatch(start.strip()):
                    break
                body = re.sub(r"<[^>]+>", "", " ".join(lines[i + 1 :]))
                body = re.sub(r"\s+", " ", body).strip()
                if body and (not cues or cues[-1][1] != body):
                    cues.append((_seconds(start), body))
                break
    return cues


@dataclass(frozen=True)
class FileVideo:
    """A local video as the sampler protocol wants it (``video_id``, ``url``, ``title``,
    ``duration``, ``license``, ``frames()``)."""

    path: Path
    every_s: float
    duration: float | None
    ffmpeg: str = "ffmpeg"
    video_id: str | None = None
    license: str | None = None

    @property
    def url(self) -> str:
        return str(self.path)

    @property
    def title(self) -> str:
        return self.path.stem

    def frames(self) -> Iterator[tuple[float, Any]]:
        from PIL import Image

        with tempfile.TemporaryDirectory(prefix="illustration-frames-") as tmp:
            subprocess.run(
                [self.ffmpeg, "-v", "error", "-i", str(self.path), "-vf", f"fps=1/{self.every_s}",
                 "-f", "image2", str(Path(tmp) / "%06d.png")],
                check=True, capture_output=True,
            )
            for i, f in enumerate(sorted(Path(tmp).glob("*.png"))):
                with Image.open(f) as image:
                    yield float(i * self.every_s), image.convert("RGB")


def _duration(path: Path, ffmpeg: str) -> float | None:
    probe = ffmpeg.replace("ffmpeg", "ffprobe")
    try:
        out = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return float(out)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def file_sampler(path: "str | Path", *, every_s: float = DFLT_EVERY_S, ffmpeg: str = "ffmpeg") -> FileVideo:
    """A local video sampled every ``every_s`` seconds: ``index_video_frames([...], sampler=file_sampler)``.

    Use ``functools.partial(file_sampler, every_s=2)`` for another interval. Raises
    ``FileNotFoundError`` for a missing file, so indexing reports it as a failure
    and goes on.
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    if every_s <= 0:
        raise ValueError("every_s must be positive")
    return FileVideo(p, every_s, _duration(p, ffmpeg), ffmpeg)


def youtube_caption_loader(url: str, *, langs: Sequence[str] = ("en",)) -> tuple[dict, list[tuple[float, str]]]:
    """``(meta, cues)`` for a YouTube video, through ``yb.download.download_youtube_subtitles``."""
    from yb.download import download_youtube_subtitles

    with tempfile.TemporaryDirectory(prefix="illustration-captions-") as tmp:
        files = download_youtube_subtitles(url, download_dir=tmp, subtitle_langs=tuple(langs))
        cues = parse_cues(Path(files[0]).read_text(errors="replace")) if files else []
    return {"url": url, "license": YOUTUBE_STANDARD_LICENSE}, cues


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def search_captions(
    text: str,
    videos: Iterable[str],
    *,
    loader: Callable[[str], tuple[Mapping, Sequence[tuple[float, str]]]] = youtube_caption_loader,
    k: int = 10,
    per_video: int = DFLT_PER_VIDEO,
    min_gap_s: float = DFLT_MIN_GAP_S,
) -> list[FrameHit]:
    """The ``k`` caption cues that best match ``text``, best first, as :class:`FrameHit`.

    A cue scores the fraction of the query's words it contains, plus 0.5 when it
    holds the whole phrase; cues with no query word are not hits. Diversified as
    :func:`illustration.frames.search_frames` is (``per_video``, ``min_gap_s``).
    ``loader(url)`` returns ``(meta, cues)``: ``meta`` may carry ``video_id``,
    ``title``, ``license``, ``author``, ``author_url``; a video it cannot read is
    skipped.
    """
    query = _tokens(text)
    if not query:
        return []
    phrase = " ".join(query)
    scored: list[tuple[float, float, Mapping, str]] = []
    for url in videos:
        try:
            meta, cues = loader(url)
        except Exception:  # noqa: BLE001 - one unreadable video is not the end
            continue
        meta = {"url": url, **meta}
        for t, cue in cues:
            words = set(_tokens(cue))
            hit = sum(w in words for w in query) / len(query)
            if hit:
                scored.append((hit + (0.5 if phrase in " ".join(_tokens(cue)) else 0.0), float(t), meta, cue))
    scored.sort(key=lambda row: (-row[0], row[1]))
    picked: list[FrameHit] = []
    taken: list[tuple[str, float]] = []
    for score, t, meta, _cue in scored:
        vid = meta.get("video_id") or meta["url"]
        if sum(v == vid for v, _ in taken) >= per_video or any(v == vid and abs(pt - t) < min_gap_s for v, pt in taken):
            continue
        code = frame_license(meta.get("license"))
        picked.append(
            FrameHit(
                video_id=meta.get("video_id") or vid,
                video_url=meta["url"],
                t=t,
                score=score,
                title=meta.get("title"),
                license=code,
                license_raw=meta.get("license"),
                attribution=_attribution(meta.get("title"), meta.get("author"), code, meta.get("license")),
                author=meta.get("author"),
                author_url=meta.get("author_url"),
            )
        )
        taken.append((vid, t))
        if len(picked) >= k:
            break
    return picked
