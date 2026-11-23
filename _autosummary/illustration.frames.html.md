# illustration.frames

Text-to-frame search over a video corpus: find *where* in a set of videos something is.

“A cartoon wall clock”, “a bedroom at night”, “Tokyo Tower”: instead of
scrubbing, index the videos’ frames once with SigLIP, then ask in words. One
more illustration source, where an “image” is `(video, t)` (#46).

```pycon
>>> from illustration.frames import index_video_frames, search_frames
>>> index_video_frames(["https://youtu.be/<id>", ...])
>>> for hit in search_frames("a cartoon wall clock", k=12):
...     print(hit.watch_url, round(hit.score, 3), hit.license)
```

**Three seams, with working defaults.**

- `sampler`: a video URL to its frames. The default,
  [`storyboard_sampler()`](#illustration.frames.storyboard_sampler), reads YouTube’s storyboard (the seek-bar
  > thumbnails, 320x180, one every few seconds) through
  > `yb.download.youtube_storyboard`: no video download, and it works where
  > video downloads hit a bot wall. Anything returning an object with
  > `video_id`, `url`, `title`, `duration`, `license` and `frames()`
  > (`(t, PIL image)` pairs) fits, e.g. frames sampled from a local file.
- `scorer`: what embeds the frames and the query. The default is the
  package’s SigLIP 2 scorer ([`illustration.reranking.SiglipScorer`](illustration.reranking.html.md#illustration.reranking.SiglipScorer),
  the `[rerank]` extra); anything with `embed_text(text)` and
  `embed_pil_images(images, *, batch)` fits (an ONNX text encoder on a
  machine without torch, for instance), and its `model_id` (if it has one)
  is recorded with the corpus: a search with another model skips those videos
  and warns, since their vectors are not comparable.
- `store`: where the corpus lives, one entry per video (its times, its
  vectors, its title and licence). Default: JSON files under the cache dir, per
  model, since a corpus is regenerable.

**Limits to know.** A storyboard frame stands for a few seconds and can lag
the moment it shows by about a second, so cut the real frame from a few
candidate times around a hit (`yb.download`’s `start`/`end`). At 320x180
it finds scenes, not small props; a caption track can find what the picture
cannot (search both).

**Licence.** A hit carries the package’s full rights record
([`illustration.schema.RIGHTS_FIELDS`](illustration.schema.html.md#illustration.schema.RIGHTS_FIELDS)): the licence as the canonical
code of [`illustration.licensing.normalize_license()`](illustration.licensing.html.md#illustration.licensing.normalize_license) (YouTube’s Creative
Commons licence is `by`; its standard licence, which is all rights reserved,
is `youtube-standard-license`; `None` when the sampler did not say), the
licence URL, an attribution line, the author and their page, the source page
(the video at that moment), and `cacheable=False` (the frames are never
stored, only their embeddings). Fine to find and study; republishing follows
the licence.

### Module Attributes

| [`DFLT_PER_VIDEO`](#illustration.frames.DFLT_PER_VIDEO)   | At most this many hits from one video, so one long video cannot fill the list.   |
|-------------------------------------------------------------------|----------------------------------------------------------------------------------|
| [`DFLT_MIN_GAP_S`](#illustration.frames.DFLT_MIN_GAP_S)   | keep the best.                                                                   |

### Functions

| [`index_video_frames`](#illustration.frames.index_video_frames)(videos, \*[, store, ...])   | Embed every frame of `videos` into the corpus; return what happened.                                                                                                                                         |
|-------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`search_frames`](#illustration.frames.search_frames)(text, \*[, store, scorer, ...])  | The `k` frames that best match `text`, best first.                                                                                                                                                           |
| [`storyboard_sampler`](#illustration.frames.storyboard_sampler)(url, \*\*kwargs)            | A video's YouTube storyboard (`yb.download.youtube_storyboard`).                                                                                                                                             |
| [`default_frame_store`](#illustration.frames.default_frame_store)(model)                     | JSON files under the cache dir, one per video, per embedding model.                                                                                                                                          |
| [`frame_license`](#illustration.frames.frame_license)(raw)                             | A video licence as the package's canonical code ([`illustration.licensing.normalize_license()`](illustration.licensing.html.md#illustration.licensing.normalize_license)); `None` when unknown. |
| [`youtube_video_id`](#illustration.frames.youtube_video_id)(url)                          | The video id in a YouTube URL, or `None`: lets indexing skip a video it already has without fetching anything.                                                                                               |

### Classes

| [`FrameHit`](#illustration.frames.FrameHit)(video_id, video_url, t, score[, ...])   | One frame that matches a query: which video, when, how well, and the rights record ([`illustration.schema.RIGHTS_FIELDS`](illustration.schema.html.md#illustration.schema.RIGHTS_FIELDS)) of that video.   |
|---------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### illustration.frames.DFLT_MIN_GAP_S *= 12.0*

keep the best.

* **Type:**
  Two hits in one video closer than this (seconds) are one scene

### illustration.frames.DFLT_PER_VIDEO *= 3*

At most this many hits from one video, so one long video cannot fill the list.

### *class* illustration.frames.FrameHit(video_id, video_url, t, score, title=None, license=None, license_raw=None, license_url=None, attribution=None, author=None, author_url=None, cacheable=False)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One frame that matches a query: which video, when, how well, and the
rights record ([`illustration.schema.RIGHTS_FIELDS`](illustration.schema.html.md#illustration.schema.RIGHTS_FIELDS)) of that video.

#### *property* rights *: [dict](https://docs.python.org/3/builtins/stdtypes.html#dict)*

The rights record, by [`illustration.schema.RIGHTS_FIELDS`](illustration.schema.html.md#illustration.schema.RIGHTS_FIELDS)’ names.

#### *property* source_page_url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

the video at this moment ([`watch_url`](#illustration.frames.FrameHit.watch_url)).

* **Type:**
  The page the frame is on

#### *property* watch_url *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

The video URL opening at this frame (whole seconds).

```pycon
>>> FrameHit("v", "https://www.youtube.com/watch?v=v", 75.4, 0.2).watch_url
'https://www.youtube.com/watch?v=v&t=75s'
>>> FrameHit("v", "https://youtu.be/v", 9.0, 0.2).watch_url
'https://youtu.be/v?t=9s'
```

### illustration.frames.default_frame_store(model)

JSON files under the cache dir, one per video, per embedding model.

* **Return type:**
  [`MutableMapping`](https://docs.python.org/3/library/typing.html#typing.MutableMapping)[[`str`](https://docs.python.org/3/builtins/stdtypes.html#str), [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)]

### illustration.frames.frame_license(raw)

A video licence as the package’s canonical code
([`illustration.licensing.normalize_license()`](illustration.licensing.html.md#illustration.licensing.normalize_license)); `None` when unknown.

```pycon
>>> frame_license("Creative Commons Attribution license (reuse allowed)")
'by'
>>> frame_license(YOUTUBE_STANDARD_LICENSE), frame_license(None)
('youtube-standard-license', None)
>>> frame_license("CC BY-NC 4.0")  # a custom sampler's licence keeps its NC
'by-nc'
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)

### illustration.frames.index_video_frames(videos, \*, store=None, sampler=<function storyboard_sampler>, scorer=None, model=None, refresh=False, batch=64)

Embed every frame of `videos` into the corpus; return what happened.

A video already in the store is skipped unless `refresh=True` (for a
YouTube URL, without fetching anything), so indexing a channel again only
does the new videos. A video that cannot be read or embedded (no
storyboard, unavailable, a corrupt sheet, a scorer error) is recorded in
`failed` with the reason, nothing is written for it, and the others go
on. Frames are embedded `batch` at a time as they are read, so a long
video never sits in memory whole.

* **Returns:**
  [ids], “skipped”: [ids], “failed”: {url: why},
  “frames”: number of frames embedded}\`\`; a video’s id is its
  `video_id`, else its URL.
* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### illustration.frames.search_frames(text, , store=None, scorer=None, model=None, k=10, per_video=3, min_gap_s=12.0, videos=None)

The `k` frames that best match `text`, best first.

Diversified, because the next frame of a match is usually a match too: at
most `per_video` hits per video, and two hits closer than `min_gap_s`
in one video are one scene (the better one is kept). `videos` limits the
search to those video ids (or URLs, for a video that has no id). Videos
indexed with another embedding model are skipped, with a warning.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FrameHit`](#illustration.frames.FrameHit)]

### illustration.frames.storyboard_sampler(url, \*\*kwargs)

A video’s YouTube storyboard (`yb.download.youtube_storyboard`).

A YouTube video with no licence reported is under YouTube’s standard
licence, so that is what it records (`YOUTUBE_STANDARD_LICENSE`).

* **Return type:**
  [`Any`](https://docs.python.org/3/library/typing.html#typing.Any)

### illustration.frames.youtube_video_id(url)

The video id in a YouTube URL, or `None`: lets indexing skip a video it
already has without fetching anything.

```pycon
>>> youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=3")
'dQw4w9WgXcQ'
>>> youtube_video_id("https://youtu.be/a-b_cdefghi"), youtube_video_id("/films/a.mp4")
('a-b_cdefghi', None)
```

* **Return type:**
  [`str`](https://docs.python.org/3/builtins/stdtypes.html#str) | [`None`](https://docs.python.org/3/builtins/constants.html#None)
