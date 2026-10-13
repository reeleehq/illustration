"""Tests for the ImageResult schema and helpers."""

import pytest

from illustration.schema import ImageResult, check_attributions, license_allowlist


def test_defaults():
    r = ImageResult(provider="p", id="1", url="u")
    assert r.tags == []
    assert r.raw == {}
    assert r.cacheable is False
    assert r.score is None


def test_roundtrip_dump_validate():
    r = ImageResult(provider="p", id="1", url="u", license="cc0", tags=["a"], raw={"x": 1})
    again = ImageResult.model_validate(r.model_dump())
    assert again == r


def test_license_allowlist_default():
    a = ImageResult(provider="p", id="1", url="u", license="cc0")
    b = ImageResult(provider="p", id="2", url="u", license="by-nc")
    c = ImageResult(provider="p", id="3", url="u", license=None)
    kept = license_allowlist([a, b, c])
    assert [r.id for r in kept] == ["1"]


def test_license_allowlist_custom_and_case_insensitive():
    a = ImageResult(provider="p", id="1", url="u", license="BY-NC")
    kept = license_allowlist([a], allow={"by-nc"})
    assert [r.id for r in kept] == ["1"]


# --- check_attributions (illustration#22) ------------------------------------


def test_check_attributions_flags_licence_less_credit():
    bare_name = ImageResult(provider="wikimedia", id="1", url="u", license="by-sa",
                             attribution="EliziR")
    proper = ImageResult(provider="wikimedia", id="2", url="u", license="by-sa",
                          attribution="Alice / CC BY-SA 4.0, via Wikimedia Commons")
    no_attribution = ImageResult(provider="wikimedia", id="3", url="u", license="by-sa",
                                  attribution=None)
    assert [r.id for r in check_attributions([bare_name, proper, no_attribution])] == [
        "1", "3",
    ]


def test_check_attributions_does_not_flag_unlicensed_results():
    # Nothing to name a licence *for* -- license_allowlist already handles
    # "no license", so check_attributions stays silent rather than duplicating it.
    r = ImageResult(provider="p", id="1", url="u", license=None, attribution=None)
    assert check_attributions([r]) == []


def test_check_attributions_is_read_only():
    # A regression audit helper must never mutate what it inspects.
    r = ImageResult(provider="p", id="1", url="u", license="by-sa", attribution="Bob")
    before = r.model_copy()
    check_attributions([r])
    assert r == before


def test_to_search_hit_bridges_to_ir():
    ir = pytest.importorskip("ir")
    r = ImageResult(provider="openverse", id="abc", url="https://x/i.jpg",
                    description="a harbour", score=0.5)
    hit = r.to_search_hit()
    assert isinstance(hit, ir.SearchHit)
    assert hit.source == "openverse"
    assert hit.artifact_id == "abc"  # provider-native id; source carries provenance
    assert hit.score == 0.5
    assert hit.metadata["url"] == "https://x/i.jpg"  # full result rides in metadata
    # the disclosure pointer must resolve to the image URL (ir scans POINTER_KEYS)
    assert hit.pointer == "https://x/i.jpg"


# --- check_attributions: the credit must name *this* licence ------------------
@pytest.mark.parametrize(
    "license,attribution",
    [
        ("by-sa", "© Jane Doe"),  # a rights notice, not a licence
        ("by-sa", "Copyright Jane Doe"),
        ("by", "Jane Doe / CC0, via Wikimedia Commons"),  # a different licence
        ("by-sa", "Jane Doe / Public domain"),
        ("cc-by-sa-4.0", "Photo: CC Sabathia"),  # "CC" as a name, no code
        ("by-nc", "Jane / CC BY 4.0"),  # drops the NC restriction
    ],
)
def test_check_attributions_flags_credit_naming_the_wrong_or_no_licence(
    license, attribution
):
    r = ImageResult(provider="p", id="1", url="u", license=license,
                    attribution=attribution)
    assert check_attributions([r]) == [r]


@pytest.mark.parametrize(
    "license,attribution",
    [
        ("by-sa", "Alice / CC BY-SA 4.0, via Wikimedia Commons"),
        ("cc-by-sa-4.0", "Jane, CC-BY-SA-4.0"),
        ("by-sa", "Jane Doe, Creative Commons Attribution-ShareAlike 4.0"),
        ("by-nc-nd", "Jane / CC BY-NC-ND 3.0"),
        ("CC BY-SA 3.0 DE", "Jane / CC BY-SA 3.0 DE"),  # jurisdiction port
        ("by-sa", "Jane / CC BY - SA"),
        ("CC0 1.0", "Joost Evers / Anefo / CC0, via Wikimedia Commons"),
        ("Pixabay License", "Jane on Pixabay (Pixabay License)"),
    ],
)
def test_check_attributions_passes_credit_naming_its_licence(license, attribution):
    r = ImageResult(provider="p", id="1", url="u", license=license,
                    attribution=attribution)
    assert check_attributions([r]) == []


def test_check_attributions_accepts_the_licence_url_in_the_credit():
    url = "https://creativecommons.org/licenses/by-sa/4.0/"
    r = ImageResult(provider="p", id="1", url="u", license="by-sa",
                    license_url=url, attribution=f"Jane Doe ({url})")
    assert check_attributions([r]) == []


# --- MediaResult / VideoResult (#32) -----------------------------------------

from illustration.schema import (  # noqa: E402
    MEDIA_RIGHTS_FIELDS,
    RIGHTS_FIELDS,
    VIDEO_RIGHTS_FIELDS,
    ImageResult,
    MediaResult,
    Rendition,
    TimeSpan,
    VideoResult,
    parse_media_result,
    require_image,
)


def _video(**kw):
    return VideoResult(
        provider="pexels",
        id="v1",
        url="https://x/v.mp4",
        duration_s=12.5,
        fps=29.97,
        has_audio=False,
        renditions=[Rendition(url="https://x/v.mp4", mime_type="video/mp4", height=1080)],
        poster_url="https://x/p.jpg",
        preview_frames=["https://x/f1.jpg"],
        moment=TimeSpan(start=1.0, end=4.5),
        license="pexels",
        editorial_only=False,
        has_model_release=True,
        has_property_release=None,
        audio_policy="no-music",
        **kw,
    )


def test_a_video_is_not_an_image_and_neither_subclasses_the_other():
    assert not issubclass(VideoResult, ImageResult)
    assert not issubclass(ImageResult, VideoResult)
    assert issubclass(ImageResult, MediaResult) and issubclass(VideoResult, MediaResult)
    assert not isinstance(_video(), ImageResult)


def test_media_type_tags():
    assert ImageResult(provider="p", id="1", url="u").media_type == "image"
    assert _video().media_type == "video"


def test_image_dump_is_unchanged_by_the_tag():
    """The image contract carries no new key: stored payloads and fixtures stay valid."""
    assert "media_type" not in ImageResult(provider="p", id="1", url="u").model_dump()


def test_video_round_trips_through_dump_and_validate():
    v = _video()
    again = VideoResult.model_validate(v.model_dump())
    assert again == v
    assert again.moment == TimeSpan(start=1.0, end=4.5)
    assert again.renditions[0].height == 1080
    assert VideoResult.model_validate_json(v.model_dump_json()) == v


def test_union_picks_the_branch_and_defaults_an_untagged_payload_to_image():
    untagged = {"provider": "p", "id": "1", "url": "u"}
    assert type(parse_media_result(untagged)) is ImageResult
    assert type(parse_media_result({**untagged, "media_type": "image"})) is ImageResult
    assert type(parse_media_result(_video().model_dump())) is VideoResult
    img = ImageResult(provider="p", id="1", url="u")
    assert parse_media_result(img) is img  # instances pass through


def test_union_rejects_an_unknown_media_type():
    with pytest.raises(Exception):
        parse_media_result({"provider": "p", "id": "1", "url": "u", "media_type": "audio"})


def test_video_rights_fields_join_the_media_rights_record():
    assert VIDEO_RIGHTS_FIELDS == (
        "editorial_only",
        "has_model_release",
        "has_property_release",
        "audio_policy",
    )
    assert MEDIA_RIGHTS_FIELDS == RIGHTS_FIELDS + VIDEO_RIGHTS_FIELDS
    assert set(VIDEO_RIGHTS_FIELDS) <= set(VideoResult.model_fields)
    # none of them is claimed for images
    assert not set(VIDEO_RIGHTS_FIELDS) & set(ImageResult.model_fields)
    assert all(getattr(_video(), f) is None for f in ("has_property_release",))


def test_require_image_refuses_a_video_by_name():
    with pytest.raises(TypeError, match="expects an ImageResult, got VideoResult"):
        require_image(_video(), where="the thing")
    img = ImageResult(provider="p", id="1", url="u")
    assert require_image(img) is img


def test_license_gate_works_on_videos_too():
    from illustration.schema import license_allowlist

    ok = VideoResult(provider="p", id="1", url="u", license="cc0")
    no = VideoResult(provider="p", id="2", url="u", license=None)
    assert license_allowlist([ok, no]) == [ok]


def test_union_json_schema_has_oneof_and_a_discriminator_mapping():
    import json
    from pathlib import Path

    schema = json.loads(
        (Path(__file__).parent.parent / "schema" / "media-result.schema.json").read_text()
    )
    assert [b["$ref"] for b in schema["oneOf"]] == [
        "#/$defs/ImageResult",
        "#/$defs/VideoResult",
    ]
    assert schema["discriminator"] == {
        "propertyName": "media_type",
        "mapping": {"image": "#/$defs/ImageResult", "video": "#/$defs/VideoResult"},
    }
    assert schema["$defs"]["VideoResult"]["properties"]["media_type"]["const"] == "video"
    assert schema["$defs"]["ImageResult"]["properties"]["media_type"]["default"] == "image"


def test_timespan_must_be_ordered():
    with pytest.raises(ValueError):
        TimeSpan(start=5, end=1)
    assert TimeSpan(start=2, end=2).end == 2


def test_the_search_cache_hands_a_video_back_as_a_video_with_its_rights():
    from illustration.caching import SearchCache

    cache = SearchCache({})
    cache.put("s", "q", {}, [_video()])
    (back,) = cache.get("s", "q", {})
    assert type(back) is VideoResult and back == _video()
    assert back.editorial_only is False and back.audio_policy == "no-music"


def test_an_untagged_payload_validates_against_exactly_one_branch_of_the_exported_schema():
    jsonschema = pytest.importorskip("jsonschema")
    import json
    from pathlib import Path

    schema = json.loads(
        (Path(__file__).parent.parent / "schema" / "media-result.schema.json").read_text()
    )
    jsonschema.validate({"provider": "p", "id": "1", "url": "u"}, schema)
    jsonschema.validate(_video().model_dump(mode="json"), schema)


def test_sequence_and_dedupe_refuse_a_video_before_doing_any_work():
    from illustration.duplicates import dedupe
    from illustration.sequence import select_sequence

    hashed = []
    with pytest.raises(TypeError, match="select_sequence expects an ImageResult"):
        select_sequence([[_video()]], hasher=lambda img: hashed.append(img) or 0)
    assert hashed == []
    with pytest.raises(TypeError, match="group_duplicates"):
        dedupe([_video(), _video()])
