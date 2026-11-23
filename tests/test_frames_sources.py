"""Frames from a local file, caption search, and the stacked index (#59)."""

import shutil
import subprocess

import pytest

np = pytest.importorskip("numpy")

from illustration.frames import FrameIndex, index_video_frames, search_frames  # noqa: E402
from illustration.frames_sources import file_sampler, parse_cues, search_captions  # noqa: E402

from test_frames import FakeScorer, VIDEOS, _sampler  # noqa: E402

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.500
I found my <c>held</c> mug

00:00:03.500 --> 00:00:05.000
I found my held mug

00:01:10.250 --> 00:01:12.000
the tower at night
"""


def test_parse_cues_strips_markup_and_collapses_repeats():
    assert parse_cues(VTT) == [(1.0, "I found my held mug"), (70.25, "the tower at night")]
    srt = "1\n00:00:02,000 --> 00:00:04,000\nhello\n"
    assert parse_cues(srt) == [(2.0, "hello")]


def _loader(url):
    return {"video_id": "c1", "title": "Mugs", "license": None}, parse_cues(VTT)


def test_caption_search_returns_frame_hits_at_the_cue_time():
    hits = search_captions("held mug", ["u"], loader=_loader)
    assert [(h.video_id, h.t) for h in hits] == [("c1", 1.0)]  # the repeat is one cue
    assert hits[0].score > 1 and hits[0].watch_url.endswith("?t=1s")
    assert search_captions("zzz", ["u"], loader=_loader) == []
    assert search_captions("mug", ["bad"], loader=lambda u: 1 / 0) == []


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="needs ffmpeg")
def test_file_sampler_yields_a_frame_every_n_seconds(tmp_path):
    pytest.importorskip("PIL")
    video = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x48:rate=5:duration=7", str(video)],
        check=True,
    )
    clip = file_sampler(video, every_s=2)
    assert clip.url == str(video.resolve()) and clip.video_id is None and clip.title == "clip"
    frames = list(clip.frames())
    assert [t for t, _ in frames] == [0.0, 2.0, 4.0, 6.0]
    assert frames[0][1].size == (64, 48)
    with pytest.raises(FileNotFoundError):
        file_sampler(tmp_path / "missing.mp4")


def test_a_prebuilt_index_answers_like_the_store():
    store, scorer = {}, FakeScorer()
    index_video_frames(["u1", "u2"], store=store, sampler=_sampler, scorer=scorer)
    index = FrameIndex.from_store(store)
    assert index.frames == 7
    from_store = search_frames("clock", store=store, scorer=scorer, k=10)
    from_index = search_frames("clock", index=index, scorer=scorer, k=10)
    assert [(h.video_id, h.t, h.score) for h in from_index] == [(h.video_id, h.t, h.score) for h in from_store]
    with pytest.raises(ValueError, match="built for model"):
        search_frames("clock", index=index, scorer=scorer, model="other-model")
