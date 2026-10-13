# illustration.providers.wikimedia

Wikimedia Commons source — 140M+ free media, **no key**, deep file metadata.

Wikimedia Commons (the MediaWiki Action API at
`https://commons.wikimedia.org/w/api.php`) adds breadth and historical /
editorial / fine-art / scientific reference imagery to the no-key default set.
It uses a `generator=search` query feeding `prop=imageinfo` so each hit
carries the full image URL, a thumbnail, and `extmetadata` (license, license
URL, artist, attribution).

This adapter exercises the base’s general extension hooks (no per-provider hacks
in the façade): `fixed_params` (the constant `action=query` / `format`
/ `generator` / `gsrnamespace` / `prop` / `iiprop` params) and
`_page_params()` (Wikimedia paginates by `gsroffset`, not page number).

Quirks handled here: the response’s `query.pages` is a \*\*dict keyed by
pageid\*\* (sorted here by the search `index` to preserve relevance order);
licenses **vary per file** (so pair with the `license_allow` gate for
commercial use); the `Artist` field is **HTML** (stripped for `author`,
with the first `href` lifted into `author_url`); the File namespace includes
non-images (PDF/audio/video) which are dropped during normalization by MIME.

It supports **none** of the canonical search-time filters (orientation/size/
safe/license_type/color/content_type) — they degrade gracefully.

### Functions

| [`thumbnail_at_width`](#illustration.providers.wikimedia.thumbnail_at_width)(url, width, \*[, ...])   | Rewrite a Commons thumbnail URL to render at `width` px.   |
|----------------------------------------------------------------------------------------------|------------------------------------------------------------|

### Classes

| [`WikimediaSource`](#illustration.providers.wikimedia.WikimediaSource)(\*[, session])   | Pure-search adapter for Wikimedia Commons (MediaWiki Action API).   |
|-----------------------------------------------------------------------------------|---------------------------------------------------------------------|

### *class* illustration.providers.wikimedia.WikimediaSource(, session=None)

Bases: [`RetrievalSource`](illustration.base.html.md#illustration.base.RetrievalSource)

Pure-search adapter for Wikimedia Commons (MediaWiki Action API).

#### api_user_agent *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= True*

Whether this API asks for (and its CORS preflight accepts) an
`Api-User-Agent` header. A browser cannot set `User-Agent`, and an
extra non-simple header makes it preflight, which a source that does not
list the header refuses; so the TS twin sends it to flagged sources only.

#### endpoint *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'https://commons.wikimedia.org/w/api.php'*

Search endpoint URL. Required.

#### fixed_params *: [Mapping](https://docs.python.org/3/library/typing.html#typing.Mapping)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), [Any](https://docs.python.org/3/library/typing.html#typing.Any)]* *= {'action': 'query', 'format': 'json', 'formatversion': '2', 'generator': 'search', 'gsrnamespace': '6', 'iiprop': 'url|extmetadata|size|mime|user', 'iiurlwidth': '320', 'origin': '\*', 'prop': 'imageinfo'}*

Constant native params sent on every request (e.g. an API mode/format).

#### info *: [SourceInfo](illustration.base.html.md#illustration.base.SourceInfo)* *= SourceInfo(name='wikimedia', description='140M+ free media files with deep per-file metadata; no key.', requires_key=False, homepage='https://commons.wikimedia.org', default_cacheable=True, license_note='Per-file license varies (CC/PD; some share-alike) — gate for commercial use.', rate_limit='etiquette-bound (descriptive User-Agent required)', tags=('open', 'historical', 'editorial', 'breadth', 'no-key'))*

Static metadata (a per-instance one is synthesized in \_\_init_\_ if unset).

#### max_per_page *: [int](https://docs.python.org/3/builtins/functions.html#int)* *= 50*

Hard cap on results per page this provider allows.

#### name *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'wikimedia'*

Registry key, e.g. `"openverse"`. Required.

#### query_param *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)* *= 'gsrsearch'*

Native name of the free-text query parameter.

### illustration.providers.wikimedia.thumbnail_at_width(url, width, , original_width=None)

Rewrite a Commons thumbnail URL to render at `width` px.

Fetching the 15 MB original just to downscale it is the slow path, and
`upload.wikimedia.org` serves arbitrary widths of any thumbnail URL. Only
URLs already in `/thumb/` form on the upload host are touched (anything
else comes back unchanged), and a `width` above `original_width` is left
alone because the service answers 400 to an upscale.

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

```pycon
>>> u = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/320px-X.jpg"
>>> thumbnail_at_width(u, 1280)
'https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/1280px-X.jpg'
>>> thumbnail_at_width(u, 1280, original_width=900) == u
True
>>> thumbnail_at_width("https://example.org/a.jpg", 1280)
'https://example.org/a.jpg'
```
