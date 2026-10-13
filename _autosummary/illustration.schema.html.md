# illustration.schema

The normalized result schema — the single source of truth (Pydantic v2).

[`ImageResult`](#illustration.schema.ImageResult) is the stable contract that every provider normalizes into
and that the (future) agentic curation layer consumes. License, attribution,
`source_page_url` and `cacheable` are first-class and populated from day one,
because licensing/cacheability is a primary concern for commercial-adjacent
video (see `misc/docs/design/illustration_design.md` §3).

```pycon
>>> r = ImageResult(provider="openverse", id="abc", url="https://x/img.jpg",
...                  license="by-sa", cacheable=True)
>>> r.provider, r.cacheable, r.tags
('openverse', True, [])
>>> r.model_dump()["license"]
'by-sa'
```

The `raw` field carries the untranslated provider payload (the escape-hatch
“nothing is lost” convention), so a downstream consumer can always reach a
provider-specific field the normalized schema doesn’t name.

### Module Attributes

| [`RIGHTS_FIELDS`](#illustration.schema.RIGHTS_FIELDS)       | the fields that answer "may we ship this, and whom must we credit?".                                             |
|----------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------|
| [`VIDEO_RIGHTS_FIELDS`](#illustration.schema.VIDEO_RIGHTS_FIELDS) | The extra rights flags a **video** hit carries (stock footage is licensed with restrictions a photo rarely has). |
| [`MEDIA_RIGHTS_FIELDS`](#illustration.schema.MEDIA_RIGHTS_FIELDS) | Everything that answers "may we ship this?" for *any* media type — what persistence stores.                      |
| [`MEDIA_TYPES`](#illustration.schema.MEDIA_TYPES)         | The values of the `media_type` tag, in union order.                                                              |
| [`AnyMediaResult`](#illustration.schema.AnyMediaResult)      | Either kind of hit.                                                                                              |

### Functions

| [`parse_media_result`](#illustration.schema.parse_media_result)(obj)                 | Validate a dict (or pass through a model) into the right result type.                                          |
|------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------|
| [`require_image`](#illustration.schema.require_image)(obj, \*[, where, strict]) | Return `obj` if it is an [`ImageResult`](#illustration.schema.ImageResult), else raise `TypeError`. |
| [`license_allowlist`](#illustration.schema.license_allowlist)(results, \*[, allow]) | Keep only results whose license is on the allowlist (R3's license gate).                                       |
| [`check_attributions`](#illustration.schema.check_attributions)(results)             | Return the results whose `attribution` does not visibly name a licence.                                        |
| [`to_search_hit`](#illustration.schema.to_search_hit)(result)                   | Map an [`ImageResult`](#illustration.schema.ImageResult) to an `ir.SearchHit` for Layer-2 fusion.   |

### Classes

| [`MediaResult`](#illustration.schema.MediaResult)(\*\*data)   | What every normalized hit from any provider carries, whatever the media.   |
|--------------------------------------------------------------------------|----------------------------------------------------------------------------|
| [`ImageResult`](#illustration.schema.ImageResult)(\*\*data)   | One normalized image hit from any provider.                                |
| [`VideoResult`](#illustration.schema.VideoResult)(\*\*data)   | One normalized video hit from any provider.                                |
| [`Rendition`](#illustration.schema.Rendition)(\*\*data)     | One playable encoding of a video, as a provider offers it.                 |
| [`TimeSpan`](#illustration.schema.TimeSpan)(\*\*data)      | A span of a media file, in seconds.                                        |

### illustration.schema.AnyMediaResult

Either kind of hit. Discriminated by `media_type`; a payload without the
tag is an image, so every stored selection and cached result still loads.

alias of `Annotated`[`Annotated`[[`ImageResult`](#illustration.schema.ImageResult), `Tag`(tag=image)] | `Annotated`[[`VideoResult`](#illustration.schema.VideoResult), `Tag`(tag=video)], `Discriminator`(discriminator=`_media_type_of`, custom_error_type=[`None`](https://docs.python.org/3/builtins/constants.html#None), custom_error_message=[`None`](https://docs.python.org/3/builtins/constants.html#None), custom_error_context=[`None`](https://docs.python.org/3/builtins/constants.html#None))]

### *class* illustration.schema.ImageResult(\*\*data)

Bases: [`MediaResult`](#illustration.schema.MediaResult)

One normalized image hit from any provider.

The first eight fields plus `cacheable` are the cross-provider minimum the
design guarantees; the rest are populated when a provider supplies them.

#### *property* media_type *: [Literal](https://docs.python.org/3/library/typing.html#typing.Literal)['image']*

Always `"image"`; deliberately not a serialized field (see [`MediaResult`](#illustration.schema.MediaResult)).

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### illustration.schema.MEDIA_RIGHTS_FIELDS *= ('license', 'license_url', 'attribution', 'source_page_url', 'author', 'author_url', 'cacheable', 'editorial_only', 'has_model_release', 'has_property_release', 'audio_policy')*

Everything that answers “may we ship this?” for *any* media type — what
persistence stores. For an image the last four are simply never recorded.

### illustration.schema.MEDIA_TYPES *= ('image', 'video')*

The values of the `media_type` tag, in union order.

### *class* illustration.schema.MediaResult(\*\*data)

Bases: `BaseModel`

What every normalized hit from any provider carries, whatever the media.

A base, not a result: instantiate [`ImageResult`](#illustration.schema.ImageResult) or
[`VideoResult`](#illustration.schema.VideoResult). Neither subclasses the other, on purpose — code typed
on images (the `burns` render hook, `sequence`’s pHash dedupe) must not
silently accept a video; see [`require_image()`](#illustration.schema.require_image).

`media_type` tells them apart: `"image"` or `"video"`. It is a real
serialized field on [`VideoResult`](#illustration.schema.VideoResult) only. [`ImageResult`](#illustration.schema.ImageResult) reports
`"image"` through a read-only property and does not serialize it, so the
image contract (dumps, JSON Schema, stored selections, parity fixtures) is
byte-for-byte what it was; a payload with no tag *is* an image
([`parse_media_result()`](#illustration.schema.parse_media_result)).

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

#### to_search_hit()

Adapt to an `ir.SearchHit` for Layer-2 cross-provider fusion.

Imported lazily so `import illustration` never requires `ir`.

### illustration.schema.RIGHTS_FIELDS *= ('license', 'license_url', 'attribution', 'source_page_url', 'author', 'author_url', 'cacheable')*

the fields that answer “may we ship this, and whom
must we credit?”. This tuple is the SSOT for that question — anything that
persists, forwards or re-materialises an [`ImageResult`](#illustration.schema.ImageResult) copies exactly
these, by these names, so no rename table is ever needed downstream. It is
the one field set that cannot be reconstructed later: a dead URL, a
re-keyed provider or a re-tagged aggregator all leave a stored selection
unable to answer it.

* **Type:**
  The **rights record**

### *class* illustration.schema.Rendition(\*\*data)

Bases: `BaseModel`

One playable encoding of a video, as a provider offers it.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* illustration.schema.TimeSpan(\*\*data)

Bases: `BaseModel`

A span of a media file, in seconds.

Maps onto an OTIO `TimeRange`, a schema.org `Clip` and a media-fragment
`#t=start,end`.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### illustration.schema.VIDEO_RIGHTS_FIELDS *= ('editorial_only', 'has_model_release', 'has_property_release', 'audio_policy')*

The extra rights flags a **video** hit carries (stock footage is licensed
with restrictions a photo rarely has). They answer the same question as
[`RIGHTS_FIELDS`](#illustration.schema.RIGHTS_FIELDS) and are persisted under the same names, but they live
beside it rather than inside it: [`RIGHTS_FIELDS`](#illustration.schema.RIGHTS_FIELDS) is what an *image*
has, and it is projected wholesale onto `walkthru.AssetRights` and read off
every [`ImageResult`](#illustration.schema.ImageResult). All four are optional; `None` means \*not
recorded\*, which is not the same claim as `False`.

### *class* illustration.schema.VideoResult(\*\*data)

Bases: [`MediaResult`](#illustration.schema.MediaResult)

One normalized video hit from any provider.

Carries the [`MediaResult`](#illustration.schema.MediaResult) fields plus what is specific to footage.
`url` stays the best *progressive* rendition at search time, so a reader
of `.url` keeps working; `renditions` lists every encoding on offer.

The four [`VIDEO_RIGHTS_FIELDS`](#illustration.schema.VIDEO_RIGHTS_FIELDS) are optional; `None` means \*not
recorded\*.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### illustration.schema.check_attributions(results)

Return the results whose `attribution` does not visibly name a licence.

`license_allowlist` gates on the *machine-readable* `license` field;
this is the companion audit for the *human-readable* `attribution`
string a credit roll actually renders. CC BY / CC BY-SA require the
licence to be identified in the credit — a licensed result with a
populated, correct `license` can still carry an `attribution` that is
just an author’s name (illustration#22, seen on ~4% of one Wikimedia
session’s hits), which silently breaches that condition if a consumer
renders `attribution` verbatim, as the package’s own guide tells them
to. This never rewrites or drops a result — it is read-only, for a
pipeline to review, log, or compose a fallback credit from `author` /
`license` / `license_url` for exactly the results it returns.

What counts as “naming the licence” depends on the licence. For the
CC BY family (`by`, `by-sa`, `by-nc`, …) the attribution must name
*that* licence (see [`illustration.licensing.licenses_named()`](illustration.licensing.html.md#illustration.licensing.licenses_named)), or
contain the result’s `license_url`: “© Jane Doe”, “Public domain”, or a
different CC code (e.g. “CC BY” for a `by-nc` image, which drops the NC
restriction) are all flagged. For any other licence, the looser
[`illustration.licensing.mentions_license()`](illustration.licensing.html.md#illustration.licensing.mentions_license) signal is used.

A result with no `license` at all is not flagged: there is nothing to
name, and it should already have been dropped by `license_allowlist` if
that matters to the caller.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`MediaResult`](#illustration.schema.MediaResult)]

```pycon
>>> a = ImageResult(provider="p", id="1", url="u", license="by-sa", attribution="Jane Doe")
>>> b = ImageResult(provider="p", id="2", url="u", license="by-sa",
...                  attribution="Jane Doe / CC BY-SA 4.0, via Wikimedia Commons")
>>> c = ImageResult(provider="p", id="3", url="u", license=None, attribution=None)
>>> [r.id for r in check_attributions([a, b, c])]
['1']
```

### illustration.schema.license_allowlist(results, , allow=None)

Keep only results whose license is on the allowlist (R3’s license gate).

The mandatory per-file license-verification gate for commercial-adjacent
use: aggregators disclaim license accuracy, so callers should gate on a
known-good set. Both sides are run through
[`illustration.licensing.normalize_license()`](illustration.licensing.html.md#illustration.licensing.normalize_license) first, so a provider’s own
spelling (`cc-by-sa-4.0` from Commons, `Pixabay License`) matches the
canonical code without the allowlist having to enumerate every dialect —
and without ever dropping an `nc`/`nd` restriction. Results with no
`license` are dropped (unknown == not allowed).

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`MediaResult`](#illustration.schema.MediaResult)]

```pycon
>>> a = ImageResult(provider="p", id="1", url="u", license="cc0")
>>> b = ImageResult(provider="p", id="2", url="u", license="by-nc")
>>> c = ImageResult(provider="p", id="3", url="u", license=None)
>>> [r.id for r in license_allowlist([a, b, c])]
['1']
>>> [r.id for r in license_allowlist([a, b, c], allow={"by-nc"})]
['2']
```

Provider dialects pass the same gate:

```pycon
>>> w = ImageResult(provider="wikimedia", id="4", url="u", license="cc-by-sa-4.0")
>>> p = ImageResult(provider="pixabay", id="5", url="u", license="Pixabay License")
>>> nd = ImageResult(provider="wikimedia", id="6", url="u", license="cc-by-nd-4.0")
>>> [r.id for r in license_allowlist([w, p, nd])]
['4', '5']
```

### illustration.schema.parse_media_result(obj)

Validate a dict (or pass through a model) into the right result type.

* **Return type:**
  [`ImageResult`](#illustration.schema.ImageResult) | [`VideoResult`](#illustration.schema.VideoResult)

```pycon
>>> parse_media_result({"provider": "p", "id": "1", "url": "u"}).media_type
'image'
>>> parse_media_result({"provider": "p", "id": "1", "url": "u", "media_type": "video"}).media_type
'video'
```

### illustration.schema.require_image(obj, , where='this function', strict=True)

Return `obj` if it is an [`ImageResult`](#illustration.schema.ImageResult), else raise `TypeError`.

`strict=False` refuses only other [`MediaResult`](#illustration.schema.MediaResult) kinds (a video) and
lets a duck-typed stand-in through, for call sites that always took those.

The guard for image-only code paths. A [`VideoResult`](#illustration.schema.VideoResult) is not an
[`ImageResult`](#illustration.schema.ImageResult) by design, but duck-typed code that reads `.url` would
take one without complaint and fetch a movie as a picture; this makes that
loud.

* **Return type:**
  [`ImageResult`](#illustration.schema.ImageResult)

```pycon
>>> require_image(VideoResult(provider="p", id="1", url="u"), where="render")
Traceback (most recent call last):
...
TypeError: render expects an ImageResult, got VideoResult
```

### illustration.schema.to_search_hit(result)

Map an [`ImageResult`](#illustration.schema.ImageResult) to an `ir.SearchHit` for Layer-2 fusion.

The bridge into the `ir` retrieval substrate so the agentic layer can
`ir.fuse_hits` across providers. `ir` is imported here, not at module
top, to keep the base façade dependency-light. Identity follows ir’s
`(source, artifact_id)` keying: `source` is the provider and
`artifact_id` is the provider-native id. The image URL is placed under the
`path` metadata key so `SearchHit.pointer` (which scans
`ir.base.POINTER_KEYS`) resolves to it; the full normalized result rides
along in `metadata` too.

`score` is `0.0` for any hit not yet reranked (Layer 1 leaves
`ImageResult.score` as `None`) — rely on *rank*, not magnitude, until a
Layer-2 reranker populates it; `ir.fuse_hits` (RRF) is rank-based, so this
is correct for fusion.
