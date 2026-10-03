# Attribution and third-party notices

WWNN is a fork of **MoneyPrinterTurbo** by harry0703 and contributors
(https://github.com/harry0703/MoneyPrinterTurbo), forked at upstream commit
`01e9ecc` (3 Oct 2026). MoneyPrinterTurbo is released under the MIT License; the
original copyright notice is kept unchanged in [`LICENSE`](LICENSE) and applies to
all code that originates from MoneyPrinterTurbo.

## What was kept from MoneyPrinterTurbo

| Path | Status |
|---|---|
| `app/services/subtitle.py` | Kept. faster-whisper transcription (`create()`) and script re-alignment (`correct()`); WWNN adds a forced `language`. Used by `wwnn/compose/subtitles.py` when `WWNN_SUBTITLE_PROVIDER=whisper`. |
| `app/utils/subtitle_writer.py` | Kept unchanged. Atomic SRT writes; used by WWNN's subtitle builder. |
| `app/utils/utils.py` | Kept. `text_to_srt()`, `time_convert_seconds_to_hmsm()`, `split_string_by_punctuations()` are reused. |
| `app/utils/logging_utils.py`, `app/models/const.py` | Kept unchanged (dependencies of the above). |
| `app/config/config.py` | Replaced by a minimal, read-only environment shim. |
| `resource/fonts/BeVietnamPro-*.ttf`, `Charm-*.ttf` | Kept (SIL Open Font License 1.1, Google Fonts). |
| `tests/upstream/test_mpt_subtitle.py` | Kept upstream test for the subtitle service. |

## What was removed and why

- Stock-footage fetching (`material*.py`: Pexels, Pixabay, Coverr) and every
  commercial generative/TTS/LLM provider client (`voice.py`, `llm.py`,
  `loomloom.py`, `muapi.py`, `ofox.py`, `sonilo.py`, `twelvelabs.py`,
  `volcengine_seedance.py`, `metaso_minimax.py`, `elevenlabs_music.py`).
  The WWNN pipeline must not call commercial generative APIs.
- `upload_post.py`: cross-posting via the third-party Upload-Post SaaS, with YouTube
  privacy defaulting to `public`. Replaced by `wwnn/upload/youtube.py`
  (official YouTube Data API v3, private only).
- `video.py` (MoviePy compositor): its `combine_videos()` slices footage into ≤5 s
  shuffled sub-clips, which destroys lip-sync on avatar footage, and its BGM is a
  fixed gain without ducking. Compositing is now done with FFmpeg filtergraphs in
  `wwnn/compose/` (real sidechain ducking, libass subtitles, VHS filter).
- WebUI, FastAPI server, task manager, version checker, Docker files, bundled music
  (`resource/songs`, of unclear copyright) and proprietary fonts (Microsoft YaHei,
  STHeiti, UTM Kabel KT).

## Other projects used at runtime (not vendored)

| Project | License | Use |
|---|---|---|
| meituan-longcat/LongCat-Video (+ LongCat-Video-Avatar-1.5 weights) | MIT | Avatar rendering, invoked as a subprocess in the `longcat` container |
| resemble-ai/chatterbox | MIT | English TTS with voice cloning in the `tts` container |
| Ollama + an open-weights model of your choice | MIT / model license | Script writing and story safety classification |
| python-telegram-bot | LGPL-3.0 | Human-in-the-loop bot |
| google-api-python-client | Apache-2.0 | YouTube Data API v3 upload |
| FFmpeg | LGPL/GPL | Compositing |
