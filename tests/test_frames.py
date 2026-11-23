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
    uploader: str | None = None
    channel_url: str | None = None

    def frames(self):
        yield from self.shown


@dataclass(frozen=True)
class FakeBoard:
    video_id: str
    url: str
    title: str
    duration: float
    license: str | None
    shown: tuple


VIDEOS = {
    "u1": FakeVideo("v1", "https://www.youtube.com/watch?v=v1", "One", 60.0, None,
                    [(0.0, "bed"), (5.0, "clock"), (10.0, "clock"), (40.0, "clock"), (45.0, "tower")]),
    "u2": FakeVideo("v2", "https://youtu.be/v2", "Two", 30.0,
                    "Creative Commons Attribution license (reuse allowed)",
                    [(0.0, "clock"), (20.0, "bed")],
                    uploader="Studio Two", channel_url="https://www.youtube.com/channel/UC2"),
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
    assert hits["v1"].license is None  # this fake sampler did not say
    assert hits["v2"].license == "by" and hits["v2"].license_raw.startswith("Creative")
    assert hits["v2"].license_url == "https://creativecommons.org/licenses/by/3.0/"
    assert hits["v2"].attribution == '"Two" by Studio Two, CC BY'
    assert hits["v2"].author_url == "https://www.youtube.com/channel/UC2"
    assert hits["v2"].watch_url == "https://youtu.be/v2?t=0s" == hits["v2"].source_page_url
    assert hits["v2"].cacheable is False
    from illustration.schema import RIGHTS_FIELDS

    assert set(hits["v2"].rights) == set(RIGHTS_FIELDS)
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


def test_frame_license_is_the_package_s_canonical_code():
    assert frame_license("Creative Commons Attribution license (reuse allowed)") == "by"
    assert frame_license("Creative Commons Attribution-NonCommercial 4.0") != "by"
    assert frame_license("CC BY-NC 4.0") == "by-nc"
    assert frame_license(None) is None and frame_license("") is None


def test_a_youtube_video_with_no_licence_is_under_the_standard_licence(monkeypatch):
    import sys
    import types

    from illustration.frames import storyboard_sampler

    board = FakeBoard("v9", "https://youtu.be/v9", "Nine", 10.0, None, [])
    module = types.SimpleNamespace(youtube_storyboard=lambda url, **kw: board)
    monkeypatch.setitem(sys.modules, "yb.download", module)
    got = storyboard_sampler("https://youtu.be/v9")
    assert got.license == "YouTube Standard License"
    assert frame_license(got.license) == "youtube-standard-license"


# ── from the adversarial review of PR #56 ───────────────────────────────────


def test_ids_differing_only_in_dash_or_underscore_are_two_videos():
    vids = {
        "a": FakeVideo("abc-def", "https://youtu.be/abc-def", "A", 9.0, None, [(0.0, "clock")]),
        "b": FakeVideo("abc_def", "https://youtu.be/abc_def", "B", 9.0, None, [(0.0, "bed")]),
    }
    store = {}
    report = index_video_frames(["a", "b"], store=store, sampler=vids.__getitem__, scorer=FakeScorer())
    assert report["indexed"] == ["abc-def", "abc_def"] and len(store) == 2


def test_videos_without_an_id_are_told_apart_by_url():
    files = {
        f"/films/{n}.mp4": FakeVideo("", f"/films/{n}.mp4", n, 9.0, None, [(0.0, "clock")])
        for n in "abcd"
    }
    store, scorer = {}, FakeScorer()
    report = index_video_frames(list(files), store=store, sampler=files.__getitem__, scorer=scorer)
    assert report["indexed"] == list(files)
    hits = search_frames("clock", store=store, scorer=scorer, k=10)
    assert len(hits) == 4
    assert {h.video_url for h in search_frames("clock", store=store, scorer=scorer, videos=["/films/b.mp4"])} == {"/films/b.mp4"}


def test_a_video_that_breaks_mid_way_is_a_failure_and_the_rest_go_on():
    class Broken(FakeVideo):
        def frames(self):
            yield 0.0, "clock"
            raise OSError("truncated sprite sheet")

    vids = {"bad": Broken("vb", "https://youtu.be/vb", "B", 9.0, None, []), **VIDEOS}
    store = {}
    report = index_video_frames(["bad", "u1"], store=store, sampler=vids.__getitem__, scorer=FakeScorer())
    assert "OSError" in report["failed"]["bad"] and report["indexed"] == ["v1"]
    assert len(store) == 1  # nothing partial written


def test_a_youtube_video_already_indexed_is_skipped_without_fetching():
    store, calls = {}, []

    def sampler(url):
        calls.append(url)
        return FakeVideo("dQw4w9WgXcQ", url, "R", 9.0, None, [(0.0, "clock")])

    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    index_video_frames([url], store=store, sampler=sampler, scorer=FakeScorer())
    again = index_video_frames([url], store=store, sampler=sampler, scorer=FakeScorer())
    assert calls == [url] and again["skipped"] == ["dQw4w9WgXcQ"]


def test_a_search_with_another_model_skips_and_warns():
    store, scorer = {}, FakeScorer()
    index_video_frames(["u1"], store=store, sampler=_sampler, scorer=scorer)
    other = FakeScorer()
    other.model_id = "another/model"
    with pytest.warns(UserWarning, match="another model"):
        assert search_frames("clock", store=store, scorer=other) == []


def test_frames_are_embedded_in_batches_as_they_are_read():
    scorer = FakeScorer()
    seen = []
    real = scorer.embed_pil_images

    def spy(images, *, batch=64):
        seen.append(len(images))
        return real(images, batch=batch)

    scorer.embed_pil_images = spy
    index_video_frames(["u1"], store={}, sampler=_sampler, scorer=scorer, batch=2)
    assert seen == [2, 2, 1]
