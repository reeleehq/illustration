# illustration.frames_sources

More ways into the frame corpus: frames from a local file, and a video’s captions (#59).

Both fit the seams [`illustration.frames`](illustration.frames.html.md#module-illustration.frames) already has, so nothing there changes.

- [`file_sampler()`](#illustration.frames_sources.file_sampler): an every-N-seconds sampler for a local video, a `sampler=`
  for [`illustration.frames.index_video_frames()`](illustration.frames.html.md#illustration.frames.index_video_frames). Its identity is the file’s
  absolute path (the same keying as any id-less video since #56). Needs `ffmpeg`
  on the `PATH` and the `[frames]` extra’s pillow.
- [`search_captions()`](#illustration.frames_sources.search_captions): search a video’s subtitle cues beside its frames and get
  back the same [`FrameHit`](illustration.frames.html.md#illustration.frames.FrameHit), whose `t` is the cue’s
  start. A caption finds what a 320x180 storyboard frame cannot (a held mug that
  is only mentioned). Scoring is lexical, on purpose: SigLIP embeds pictures and
  short captions, not a sentence of speech. The cue source is a seam
  (`loader=`), by default [`youtube_caption_loader()`](#illustration.frames_sources.youtube_caption_loader) (`yb`).
  ```pycon
  >>> parse_cues("WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nhello <c>there</c>\n")
  [(1.0, 'hello there')]
  ```

### Module Attributes

| [`DFLT_EVERY_S`](#illustration.frames_sources.DFLT_EVERY_S)   | Seconds between sampled frames of a local video.   |
|-----------------------------------------------------------------|----------------------------------------------------|

### Functions

| [`file_sampler`](#illustration.frames_sources.file_sampler)(path, \*[, every_s, ffmpeg])        | A local video sampled every `every_s` seconds: `index_video_frames([...], sampler=file_sampler)`.   |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------|
| [`parse_cues`](#illustration.frames_sources.parse_cues)(text)                                 | `(start seconds, text)` per cue of a WebVTT or SRT file, markup removed.                            |
| [`search_captions`](#illustration.frames_sources.search_captions)(text, videos, \*[, loader, ...]) | The `k` caption cues that best match `text`, best first, as `FrameHit`.                             |
| [`youtube_caption_loader`](#illustration.frames_sources.youtube_caption_loader)(url, \*[, langs])         | `(meta, cues)` for a YouTube video, through `yb.download.download_youtube_subtitles`.               |

### illustration.frames_sources.DFLT_EVERY_S *= 5.0*

Seconds between sampled frames of a local video.

### illustration.frames_sources.file_sampler(path, , every_s=5.0, ffmpeg='ffmpeg')

A local video sampled every `every_s` seconds: `index_video_frames([...], sampler=file_sampler)`.

Use `functools.partial(file_sampler, every_s=2)` for another interval. Raises
`FileNotFoundError` for a missing file, so indexing reports it as a failure
and goes on.

* **Return type:**
  `FileVideo`

### illustration.frames_sources.parse_cues(text)

`(start seconds, text)` per cue of a WebVTT or SRT file, markup removed.

Auto-generated captions repeat each line as it grows; a cue whose text equals
the previous one is dropped.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]

### illustration.frames_sources.search_captions(text, videos, \*, loader=<function youtube_caption_loader>, k=10, per_video=3, min_gap_s=12.0)

The `k` caption cues that best match `text`, best first, as `FrameHit`.

A cue scores the fraction of the query’s words it contains, plus 0.5 when it
holds the whole phrase; cues with no query word are not hits. Diversified as
[`illustration.frames.search_frames()`](illustration.frames.html.md#illustration.frames.search_frames) is (`per_video`, `min_gap_s`).
`loader(url)` returns `(meta, cues)`: `meta` may carry `video_id`,
`title`, `license`, `author`, `author_url`; a video it cannot read is
skipped.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FrameHit`](illustration.frames.html.md#illustration.frames.FrameHit)]

### illustration.frames_sources.youtube_caption_loader(url, , langs=('en',))

`(meta, cues)` for a YouTube video, through `yb.download.download_youtube_subtitles`.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict), [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`float`](https://docs.python.org/3/builtins/functions.html#float), [`str`](https://docs.python.org/3/builtins/stdtypes.html#str)]]]
