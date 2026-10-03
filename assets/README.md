# Assets

Nothing in here is committed except this file and the `.gitkeep`s. In production, point
`WWNN_ASSETS_DIR` at a directory outside the repo (e.g. `/srv/wwnn/assets`) that has
the same layout. Paths in `.env` that start with `assets/` resolve against that directory.

`wwnn assets placeholders` writes **dummy** files for everything below, so a dry run
works out of the box. Their hashes are recorded in `PLACEHOLDERS.json`.
`wwnn assets check` lists the ones still in use, and the Sunday Telegram message warns
about them. Replace each file in place, keeping the same name, or point the env var at
your file.

| File (default path) | Env var | Format | Notes |
|---|---|---|---|
| `anchors/tom.png` | `WWNN_TOM_IMAGE` | PNG, 16:9 (e.g. 1920×1080) | Your Kling AI image of Tom, **already in the dark emerald green studio**. In LongCat's ai2v mode, the image defines the background. Medium shot, face clearly visible, mouth closed or neutral. |
| `anchors/annika.png` | `WWNN_ANNIKA_IMAGE` | PNG, 16:9 | Annika **in the dusty sepia archive**. She must be roughly **centred**: the Short is a 9:16 centre crop of her 16:9 render (adjust with `WWNN_SHORT_CROP_X`, 0–1). Keep her head and hands inside the middle ~32 % of the width. |
| `voices/tom_ref.wav` | `WWNN_TOM_VOICE_REF` | WAV, mono, ≥ 24 kHz, 10–20 s | Clean English speech, no music or reverb, in the target delivery (dry, bored, formal). **Written consent from the speaker is required.** |
| `voices/annika_ref.wav` | `WWNN_ANNIKA_VOICE_REF` | same | Precise, politely passive-aggressive. Consent required. |
| `bumpers/intro_16x9.mp4` | `WWNN_BUMPER_INTRO` | MP4 with audio, 16:9 | Show opener. Its length counts toward Video A's 3–5 min. |
| `bumpers/archive_transition_16x9.mp4` | `WWNN_BUMPER_TRANSITION` | MP4 with audio, 16:9 | Plays between Tom's handover and Annika. Not in the Short. |
| `bumpers/outro_16x9.mp4` | `WWNN_BUMPER_OUTRO` | MP4 with audio, 16:9 | End of Video A. |
| *(optional)* | `WWNN_SHORT_INTRO` | MP4, 9:16 | Sting before the Short. Counts against its 60 s, and Annika's cap shrinks accordingly. |
| `lower_thirds/tom_template.png` | `WWNN_LT_TEMPLATE_TOM` | **Transparent** PNG, full frame (1920×1080) | Bar artwork only. The story title and subtitle are drawn on top per story. Keep the text area in the lower-left third. |
| `lower_thirds/annika_template.png` | `WWNN_LT_TEMPLATE_ANNIKA` | same | |
| `bgm/news_bed.wav` | `WWNN_BGM_NEWS` | WAV/MP3, loopable | Under Tom. Sidechain-ducked under speech. **Must be licensed for YouTube.** |
| `bgm/archive_bed.wav` | `WWNN_BGM_ARCHIVE` | WAV/MP3, loopable | Under Annika (Video A and the Short). |

Bumpers are scaled and cropped to the output size, resampled to 25 fps and 48 kHz
stereo, and their audio is never ducked. Music beds are looped as needed.
