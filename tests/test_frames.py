"""Text-to-frame search over a video corpus (#46), with fake frames and a fake scorer."""

from dataclasses import dataclass

import pytest

np = pytest.importorskip("numpy")

from illustration.frames import (  # noqa: E402
    FrameHit,
    frame_license,
    index_video_frames,
    search_frames,
)

#: A frame "image" here is just the name of what it shows; the fake scorer maps
#: a name (or a query) to a fixed unit vector.
VOCAB = {"clock": [1, 0, 0], "bed": [0, 1, 0], "tower": [0, 0, 1]}


def _vec(name):
    v = np.asarray(VOCAB.get(name, [0.3, 0.3, 0.3]), dtype="float32")
    return v / np.linalg.norm(v)


class FakeScorer:
    def __init__(self):
        self.embedded = 0

    def embed_text(self, text):
        return _vec(text.split()[-1])

    def embed_pil_images(self, images, *, batch=64):
        self.embedded += len(images)
        return [_vec(name) for name in images]


@dataclass
class FakeVideo:
    video_id: str
    url: str
    title: str
    duration: float
    license: str | None
    shown: list  # (t, name)

    def frames(self):
        yield from self.shown


VIDEOS = {
    "u1": FakeVideo("v1", "https://www.youtube.com/watch?v=v1", "One", 60.0, None,
                    [(0.0, "bed"), (5.0, "clock"), (10.0, "clock"), (40.0, "clock"), (45.0, "tower")]),
    "u2": FakeVideo("v2", "https://youtu.be/v2", "Two", 30.0,
                    "Creative Commons Attribution license (reuse allowed)",
                    [(0.0, "clock"), (20.0, "bed")]),
}


def _sampler(url):
    if url not in VIDEOS:
        raise LookupError(f"{url}: no storyboard 'sb0' (has: none)")
    return VIDEOS[url]


def test_index_then_search_ranks_frames_by_meaning():
    store, scorer = {}, FakeScorer()
    report = index_video_frames(["u1", "u2", "gone"], store=store, sampler=_sampler, scorer=scorer)
    assert report["indexed"] == ["v1", "v2"] and report["frames"] == 7
    assert "LookupError" in report["failed"]["gone"]
    hits = search_frames("a cartoon clock", store=store, scorer=scorer, k=10)
    assert all(isinstance(h, FrameHit) for h in hits)
    top = [(h.video_id, h.t) for h in hits if h.score > 0.9]
    # v1's clocks at 5 and 10 s are one scene (12 s gap); 40 s is another
    assert sorted(top) == [("v1", 5.0), ("v1", 40.0), ("v2", 0.0)]


def test_hits_carry_the_video_s_licence_and_a_link_to_the_moment():
    store, scorer = {}, FakeScorer()
    index_video_frames(["u1", "u2"], store=store, sampler=_sampler, scorer=scorer)
    hits = {h.video_id: h for h in search_frames("clock", store=store, scorer=scorer, k=2, per_video=1)}
    assert hits["v1"].license == "all-rights-reserved"
    assert hits["v2"].license == "CC-BY" and hits["v2"].license_raw.startswith("Creative")
    assert hits["v2"].watch_url == "https://youtu.be/v2?t=0s"
    assert hits["v1"].title == "One"


def test_per_video_and_k_bound_the_list():
    store, scorer = {}, FakeScorer()
    index_video_frames(["u1"], store=store, sampler=_sampler, scorer=scorer)
    assert len(search_frames("clock", store=store, scorer=scorer, k=10, per_video=1)) == 1
    assert len(search_frames("clock", store=store, scorer=scorer, k=2, min_gap_s=0)) == 2


def test_an_indexed_video_is_skipped_unless_refreshed():
    store, scorer = {}, FakeScorer()
    index_video_frames(["u1"], store=store, sampler=_sampler, scorer=scorer)
    again = index_video_frames(["u1"], store=store, sampler=_sampler, scorer=scorer)
    assert again["skipped"] == ["v1"] and scorer.embedded == 5
    index_video_frames(["u1"], store=store, sampler=_sampler, scorer=scorer, refresh=True)
    assert scorer.embedded == 10


def test_search_can_be_limited_to_some_videos():
    store, scorer = {}, FakeScorer()
    index_video_frames(["u1", "u2"], store=store, sampler=_sampler, scorer=scorer)
    hits = search_frames("clock", store=store, scorer=scorer, videos=["v2"])
    assert {h.video_id for h in hits} == {"v2"}


def test_an_empty_corpus_finds_nothing():
    assert search_frames("clock", store={}, scorer=FakeScorer()) == []


def test_frame_license():
    assert frame_license("creative commons whatever") == "CC-BY"
    assert frame_license("") == "all-rights-reserved"
