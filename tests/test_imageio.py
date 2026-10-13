"""Tests for illustration._imageio (offline — fetch is stubbed)."""

from illustration._imageio import (
    fetch_image_bytes,
    image_for_result,
    memoized_image_loader,
)
from illustration.schema import ImageResult


def test_fetch_bytes_empty_url_returns_none():
    assert fetch_image_bytes("") is None


def test_image_for_result_no_url_returns_none():
    assert image_for_result(ImageResult(provider="p", id="1", url="")) is None


def test_memoized_loader_fetches_each_url_once():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return f"img:{url}"

    load = memoized_image_loader(fetch=fake_fetch)
    r1 = ImageResult(provider="p", id="1", url="u1", thumbnail_url="t1")
    r1b = ImageResult(provider="p", id="1b", url="u1b", thumbnail_url="t1")  # same thumb URL

    assert load(r1) == "img:t1"  # prefers thumbnail_url
    assert load(r1b) == "img:t1"  # same URL -> cached, not re-fetched
    assert load(r1) == "img:t1"
    assert calls == ["t1"]  # fetched exactly once


def test_memoized_loader_falls_back_to_url_when_field_missing():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return f"img:{url}"

    load = memoized_image_loader(fetch=fake_fetch)
    r = ImageResult(provider="p", id="1", url="full", thumbnail_url=None)
    assert load(r) == "img:full"
    assert calls == ["full"]


_THUMB = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/320px-X.jpg"


def test_image_for_result_width_asks_for_a_right_sized_commons_render(monkeypatch):
    import illustration._imageio as imageio

    asked = []
    monkeypatch.setattr(imageio, "fetch_image", lambda url, **kw: asked.append(url) or "img")
    r = ImageResult(provider="wikimedia", id="1", url="u", thumbnail_url=_THUMB, width=4000)
    assert image_for_result(r, width=1280) == "img"
    assert asked == [_THUMB.replace("320px", "1280px")]


def test_image_for_result_width_falls_back_when_the_resized_url_fails(monkeypatch):
    import illustration._imageio as imageio

    asked = []

    def fake(url, **kw):
        asked.append(url)
        return None if "1280px" in url else "img"

    monkeypatch.setattr(imageio, "fetch_image", fake)
    r = ImageResult(provider="wikimedia", id="1", url="u", thumbnail_url=_THUMB, width=4000)
    assert image_for_result(r, width=1280) == "img"
    assert asked == [_THUMB.replace("320px", "1280px"), _THUMB]


def test_image_for_result_width_never_upscales_or_touches_other_hosts(monkeypatch):
    import illustration._imageio as imageio

    asked = []
    monkeypatch.setattr(imageio, "fetch_image", lambda url, **kw: asked.append(url) or "img")
    small = ImageResult(provider="wikimedia", id="1", url="u", thumbnail_url=_THUMB, width=900)
    other = ImageResult(provider="p", id="2", url="u", thumbnail_url="https://e.org/320px-a.jpg")
    image_for_result(small, width=1280)
    image_for_result(other, width=1280)
    assert asked == [_THUMB, "https://e.org/320px-a.jpg"]


def test_memoized_loader_width_resizes_commons_urls_and_falls_back():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return None if "1280px" in url else f"img:{url}"

    load = memoized_image_loader(fetch=fake_fetch, width=1280)
    r = ImageResult(provider="wikimedia", id="1", url="u", thumbnail_url=_THUMB, width=4000)
    assert load(r) == f"img:{_THUMB}"
    assert calls == [_THUMB.replace("320px", "1280px"), _THUMB]
