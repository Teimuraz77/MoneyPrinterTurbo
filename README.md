# WWNN: Worldwide Weekly Nonsense News

A local-first, weekly AI news-satire pipeline. Every Sunday it proposes this week's most
harmless absurd news plus a few archive oddities on Telegram. You pick the stories. It
writes a formal, cynical, deadpan British script with a local LLM, voices both anchors
with Chatterbox, and sends you the script and audio for approval. Only after you approve
does it render the talking-head video with LongCat-Video-Avatar 1.5. It then composites
two videos and uploads both to YouTube as **private**:

| | Video A: main episode | Video B: Short |
|---|---|---|
| Format | 16:9, 1920×1080, 25 fps, **3–5 min** | 9:16, 1080×1920, **< 60 s** |
| Anchors | **Tom Blunt** (breaking news) → explicit handover *"From the Archive"* → **Annika** | **Annika** only |
| Look | Emerald news studio; Annika's segment gets a heavy **VHS** treatment | The **same** Annika segment with the **same VHS** look, centre-cropped to 9:16, plus a CTA end card |

No commercial generative APIs are used: no OpenAI, ElevenLabs, HeyGen or Edge-TTS. LLM,
TTS and avatar all run on your own GPU server. The only outside services are story
sources (RSS and the free NewsData.io tier), Telegram and the YouTube Data API.

This is a fork of [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) (MIT).
See [NOTICE.md](NOTICE.md) for what was kept, what was removed and why.

---

## ⚠ Read this first: GPU reality check

LongCat-Video-Avatar 1.5 is a large model. The numbers below come from upstream and
third-party reports. **None of them have been measured on your hardware yet.**

| GPU VRAM | Status | Setting |
|---|---|---|
| **80 GB** (A100/H100) | Comfortable. Official INT8 + distill path. | `LONGCAT_VRAM_PROFILE=standard` |
| **40–48 GB** (A6000, L40S, RTX 6000 Ada, A100-40) | **Realistic minimum.** A 40 GB card worked only with KV-cache offload to RAM. | `standard` with `LONGCAT_OFFLOAD_KV_CACHE=auto` (on below 70 GB), or `offload` |
| **24 GB** (RTX 3090/4090) | **Experimental only.** Uses the *unmerged* community [PR #115](https://github.com/meituan-longcat/LongCat-Video/pull/115) script (sequential CPU offload + torchao INT8). Its own benchmarks are inconsistent, from about 2 min to well over 5 min per 3.7 s segment. A weekly run could take 4–10+ h, or fail. | `LONGCAT_VRAM_PROFILE=lowmem24`, image built with `LONGCAT_WITH_LOWMEM_PR=1` |

**Recommendation:** use **≥ 48 GB**. At Hetzner today, that means the 96 GB GEX131 (see
"Hetzner notes" below). Treat a 24 GB card as a test bench. **Blackwell cards (all current
Hetzner GPUs, RTX 50xx) need the CUDA 12.8 / torch 2.7 image variant.** Other requirements:
- **≥ 64 GB system RAM** (128 GB recommended). The UMT5-XXL text encoder alone is
  22.7 GB, and KV-cache offload goes to RAM.
- **≥ 300 GB NVMe.** About 45 GB of LongCat weights, 15–20 GB of Ollama models, and
  about 10 GB per weekly run.
- An NVIDIA driver supporting CUDA ≥ 12.4 (≥ 12.8, i.e. driver ≥ 570, for Blackwell), plus
  `nvidia-container-toolkit`.

Expected render time at 480p, for about 4 min of A plus a ~50 s Short (~90 LongCat
segments, Annika rendered once): **~1.7 h on an H100, ~3–4 h on 40–48 GB.** 720p costs
roughly 2.5–3× more. Your real numbers are logged per shot in the `shots` table
(`render_seconds`) once the first run finishes.

---

## How a week runs

```
Sun 09:00 (systemd timer)            daily 07:00: ingest RSS + NewsData.io → taboo screen → SQLite
   │
   ▼
CREATED ─► AWAITING_SELECTION ── Telegram: 5 new + 3 archive stories, ☐/☑ toggles, Confirm / Skip
                │ (you confirm)
                ▼
           SELECTED ─► Ollama writes Tom + Annika (JSON), lint + taboo check, dynamic pacing
                ▼
           SCRIPTED ─► Chatterbox voices both anchors (voice-cloned), real durations re-checked
                ▼
           VOICED ───► Telegram: script (.md) + Tom.mp3 + Annika.mp3  [Approve] [Regenerate] [Reject]
                ▼
     AWAITING_APPROVAL ── nothing expensive happens until you tap Approve
                │ (approve)
                ▼
           APPROVED ─► LongCat ai2v, INT8 + distill, one subprocess per shot (resumable)
                ▼
           RENDERED ─► FFmpeg: bumpers, lower thirds, burned subtitles, ducked music beds,
                │      VHS on Annika only, 9:16 crop of Annika for the Short + CTA card, QC
                ▼
           COMPOSED ─► YouTube Data API v3: A first, then B with A's link; both PRIVATE,
                ▼      privacy read back from the API after upload
           UPLOADED ─► Telegram: private Studio links + review checklist ─► DONE
```

Any failure → **FAILED**, with a Telegram alert, the error and a **Resume** button.
Resuming restarts at the failed stage. Finished work is reused: TTS sentences are
cached by content hash, and finished LongCat shots are skipped by input hash.
**Regenerate** returns to SELECTED with a "fresh rewrite" note. **Reject** cancels the week.

### Dynamic pacing and the Short-length strategy

Annika's segment is mandatory, comes last in every episode, *and is the Short*. Pacing
works like this:

1. **Annika's speech is capped** at `WWNN_ANNIKA_MAX_SPEECH_S` (default 50 s). The cap is
   also limited to `WWNN_SHORT_MAX_S − CTA − optional Short intro − 0.5 s`, so the Short
   (Annika + 3.5 s CTA) always stays under 60 s. We cap the *script* rather than trimming
   video, so the Short is never cut mid-sentence.
2. Annika always opens with your top-ranked archive pick. Tom covers the selected breaking
   news first and ends with the explicit handover containing **"From the Archive"**.
3. If the estimated Video A (bumpers + Tom + Annika) is **under 3 min**, the writer pulls
   1–2 **extra archive stories** into Annika's segment, as long as she has ≥ 12 s of
   headroom under her cap. Whatever is still missing is given to Tom, who expands his
   stories. If A is **over 5 min**, the lowest-ranked news story is dropped or Tom is
   tightened. Up to `WWNN_PACING_MAX_ROUNDS` LLM rounds are allowed.
4. After TTS, the **real** durations are re-checked using a words-per-minute rate
   calibrated on the actual voices. Up to `WWNN_POST_TTS_MAX_ROUNDS` re-script rounds
   are allowed. If Annika is still over the cap, the run fails *before* any rendering,
   with a message that lets you resume from script writing.
5. QC after compositing asserts that the Short is vertical and under 60 s.

### Safety: the HARD taboo rule

No real violent crime, gore or deaths. Harmless absurd nonsense only. This is enforced
in four places:
1. A **keyword screen** (`wwnn/ingest/safety.py`) on every scraped item and every archive
   import. Its rejections are final.
2. An **Ollama classifier** (JSON, temperature 0) on whatever survives the keywords. It can
   only *remove* items, never re-admit them.
3. The **system prompt** (`wwnn/script/prompts/system_en.md`) forbids the topics outright.
4. **Script lint** re-runs the keyword screen on every generated sentence, and also
   rejects stage directions, speaker labels, brackets, emoji, URLs and hashtags.

### YouTube: private, always

- `privacyStatus` is hard-coded to `"private"` in `wwnn/upload/youtube.py`, asserted before
  every request, and **read back from the API** after upload. A mismatch raises
  `PrivacyViolation` and alerts you on Telegram. `publishAt` is refused. A SQLite
  `CHECK` constraint means the `uploads` table can only ever record `'private'`. A test
  greps the upload package to make sure no other privacy value appears there at all.
- `containsSyntheticMedia: true` is set, because the presenters are AI-generated.
- **There is no `related_video_id` in the YouTube API.** A Short's "Related video" link can
  only be set in YouTube Studio, and only once A is public or unlisted. The final Telegram
  message gives you a checklist with this step. Video A's URL is also written into the
  Short's description automatically. Note that links in Shorts descriptions are not
  clickable.
- **API audit:** until Google audits your API project, *every* API-uploaded video is locked
  to private, and you cannot publish it even manually. Apply for the
  [audit](https://support.google.com/youtube/contact/yt_api_form) early.
- Put the OAuth consent screen in **"In production"**. In "Testing" mode, refresh tokens
  expire after 7 days and the weekly upload breaks.

---

## Repository layout

```
wwnn/
  config.py            all settings (env / .env), documented in .env.example
  cli.py               `wwnn ...` commands (see below)
  db/                  SQLite schema migration, repo helpers, SAMPLE archive seed
  ingest/              RSS + NewsData.io scraper, taboo filter, dedupe, 5+3 proposal
  llm/ollama.py        minimal Ollama client (JSON-schema output, keep_alive=0)
  script/              prompts (English), JSON schema, lint, pacing, writer, offline mock
  tts/                 Chatterbox engine (english|turbo), sentence cache, timings, mock
  avatar/              LongCat wrapper: shot planning, patcher, runner, mock renderer, PATCHES.md
  compose/             FFmpeg compositor: VHS, lower thirds, ASS subtitles, ducking, timeline, CTA
  upload/              YouTube Data API v3 uploader (private only), metadata, OAuth bootstrap
  bot/                 Telegram keyboards, texts, notifier, pure callback handlers, PTB app
  orchestrator/        state machine, stages, GPU lock / Ollama unload
app/                   kept MoneyPrinterTurbo subtitle core (faster-whisper create()/correct())
docker/                app / tts / longcat Dockerfiles
docker-compose.yml     ollama + bot (long-running), tts / longcat / compose (jobs profile)
deploy/                systemd units (orchestrator, Sunday timer, daily ingest) + crontab example
tests/                 pytest suite incl. an end-to-end mocked dry run
```

## Commands

```
wwnn db migrate | db seed            create schema / load SAMPLE archive items
wwnn archive import FILE.csv|.json   import your vetted archive items (taboo-screened)
wwnn assets placeholders | check     write dummy assets / list placeholders still in use
wwnn ingest                          scrape + screen candidate stories
wwnn week                            create this week's run and push the selection (timer)
wwnn loop [--interval 30]            orchestrator service (advances runs, launches GPU jobs)
wwnn tick | status | resume RUN_ID   one pass / overview / resume a failed run
wwnn bot                             Telegram bot (buttons + /start /status /newrun /cancel)
wwnn youtube auth                    one-time OAuth consent, prints the refresh token
wwnn longcat patch [REPO_DIR]        write the patched LongCat entry script
wwnn dry-run [--fast] [--out DIR]    full pipeline on CPU with mocks -> real MP4s
```

---

## Quick start on any machine (no GPU): dry run

```bash
sudo apt install ffmpeg fonts-dejavu-core      # ffmpeg needs libass (Debian/Ubuntu builds have it)
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[bot,upload,dev]"
python -m pytest -q                            # ~105 tests, ~75 s (incl. one end-to-end render)
wwnn dry-run --fast --out /tmp/wwnn-dry        # ~1 min: 640x360 A + 360x640 Short
wwnn dry-run --out /tmp/wwnn-full              # ~5 min: full 1920x1080 A (3-5 min) + 1080x1920 Short
```

The dry run uses the offline script writer, a fake-speech TTS, a static-image "avatar"
renderer and a fake YouTube client. It auto-approves both gates and writes the Telegram
messages it *would* send to `data/telegram_outbox.jsonl`. Everything after that is the
real code path: shot planning, compositing, VHS, subtitles, ducking, loudness, QC,
private-upload assertions and the review checklist.

---

## Server setup (Hetzner GPU or any Ubuntu + NVIDIA box)

### 1. Base system

```bash
# Ubuntu 22.04/24.04 with an NVIDIA driver supporting CUDA >= 12.4
sudo apt install -y docker.io docker-compose-v2 ffmpeg python3-venv git
# NVIDIA container toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi   # sanity check

sudo useradd -m -G docker wwnn
sudo mkdir -p /srv/wwnn/{data,assets,models} && sudo chown -R wwnn /srv/wwnn
sudo -iu wwnn
git clone <your fork> /opt/wwnn && cd /opt/wwnn      # (/opt/wwnn owned by wwnn)
python3 -m venv .venv && .venv/bin/pip install -e ".[bot,upload]"
cp .env.example .env && chmod 600 .env               # fill in, see below
```

**Hetzner notes (checked against Hetzner's GPU server docs, last updated 2026-09-01)**

Hetzner's GPU machines are **dedicated servers** (the GEX line, ordered through Robot). They
are not Hetzner Cloud VMs. The current line has **no RTX 3090, 4090 or A6000**. It offers
two models, both **Blackwell**:

| Model | GPU | VRAM | RAM | Disk | WWNN profile |
|---|---|---|---|---|---|
| GEX45 | RTX PRO 4000 SFF Blackwell | 24 GB | 64 GB DDR4 | 2× 512 GB NVMe | `lowmem24`, **experimental** (see GPU table above) |
| GEX131 | RTX PRO 6000 Blackwell Max-Q | 96 GB | 256–768 GB | 2× 960 GB+ NVMe | `standard`, comfortable (no offload needed) |

- **Blackwell (sm_120) needs PyTorch ≥ 2.7 with CUDA 12.8.** LongCat and Chatterbox
  upstream both pin torch 2.6.0, which **does not run** on these cards. Uncomment the
  "BLACKWELL" block in `.env` before `docker compose build`. It switches both GPU images
  to CUDA 12.8 + torch 2.7.0. flash-attn then compiles from source, which takes longer.
  This is a deviation from upstream's tested pin. Validate it in the first GPU session.
- Older models (GEX44 with 20 GB, GEX130 with RTX 6000 Ada 48 GB) may still be running for
  existing customers, but they are no longer in the current order table. The 20 GB card is
  **below** the floor. A 48 GB Ada card would use the default (torch 2.6) images.
- If GEX131 pricing is too much for a few GPU hours a week, an hourly 48–80 GB cloud GPU
  is a reasonable alternative. On Ampere, Ada or Hopper, the default images work as is.
- Use local NVMe for `/srv/wwnn/models`. Loading weights from a network volume adds
  minutes to every shot. On a GEX45, the 2× 512 GB disks are tight but enough (keep only
  the last few runs in `data/runs`).
- Firewall: nothing has to be reachable from outside. The bot uses long polling, and
  Ollama is bound to `127.0.0.1`. Keep SSH only.

### 2. Model downloads (only what is needed, ~45 GB)

```bash
pip install -U "huggingface_hub[cli]"
M=/srv/wwnn/models/longcat
# LongCat base: tokenizer, text encoder, VAE, scheduler only (skip the 54 GB base DiT)
huggingface-cli download meituan-longcat/LongCat-Video \
  --include "tokenizer/*" "text_encoder/*" "vae/*" "scheduler/*" "*.json" \
  --local-dir $M/LongCat-Video
# Avatar 1.5: INT8 DiT, distill LoRA, scheduler, Whisper encoder (skip the 31.7 GB bf16 base)
huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.5 \
  --include "base_model_int8/*" "lora/*" "scheduler/*" "vocal_separator/*" "whisper-large-v3/*.json" \
            "whisper-large-v3/*.txt" "whisper-large-v3/model.safetensors" "*.json" \
  --local-dir $M/LongCat-Video-Avatar-1.5
```
The official script expects both folders as **siblings**: the checkpoint dir is
`/models/LongCat-Video-Avatar-1.5`, and it finds `/models/LongCat-Video` next to it.
If the loader complains about a missing Whisper file, re-run the second command without
the `whisper-large-v3` filters (+21 GB).

Ollama model (a general instruct model writes better English satire than a coder model):
```bash
docker compose up -d ollama
docker compose exec ollama ollama pull qwen2.5:32b-instruct    # 48 GB+ card; 24 GB: qwen2.5:14b-instruct
```
Chatterbox downloads its English weights from Hugging Face into
`/srv/wwnn/models/hf` on first use.

### 3. Build images

```bash
docker compose build bot compose tts                    # minutes
docker compose build longcat                            # 20-60 min (flash-attn may compile)
# 24 GB experiment: LONGCAT_WITH_LOWMEM_PR=1 docker compose build longcat
```
The LongCat image pins upstream code to `6b3f4b8` and applies WWNN's patch at build time
(see [wwnn/avatar/PATCHES.md](wwnn/avatar/PATCHES.md)). If upstream ever changes the
script, the build **fails** instead of silently mis-patching.

### 4. Assets and voices

```bash
wwnn assets placeholders        # dummies so everything runs; then replace them:
```
See [assets/README.md](assets/README.md) for formats. The essentials:
- `anchors/tom.png` and `anchors/annika.png` (your Kling AI images), **16:9**, with the anchor
  already **in** the set: the emerald studio for Tom, the sepia archive for Annika. In ai2v
  mode, the image defines the background. Keep **Annika centred** (or set
  `WWNN_SHORT_CROP_X`), because the Short is a 9:16 crop of her 16:9 render.
- `voices/tom_ref.wav` and `voices/annika_ref.wav`: 10–20 s of clean, mono English speech
  from **consenting** voice donors. Get written consent for synthetic voice use.
  Chatterbox embeds an imperceptible PerTh watermark in every generated file.
- Bumpers, lower-third templates and music beds: your CI. Music must be licensed for
  YouTube.

`wwnn assets check` (and the Sunday Telegram message) warns while dummy placeholders
are still in use.

### 5. Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token into
   `TELEGRAM_BOT_TOKEN`.
2. Send your bot any message, then get your numeric user id (e.g. from @userinfobot).
   Put it in `TELEGRAM_CHAT_ID` and `TELEGRAM_ALLOWED_USER_IDS`.
3. `docker compose up -d bot`, then send `/start` to the bot. Only whitelisted users can
   press buttons.

### 6. YouTube Data API v3

1. In Google Cloud Console: create a project, enable **YouTube Data API v3**, and configure
   the OAuth consent screen (External, then **publish it to "In production"**).
2. Create an OAuth client of type **Desktop app**. Put the client ID and secret into
   `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`.
3. `wwnn youtube auth`. It prints a URL. Sign in with the **channel's** Google account.
   On a headless server, use the SSH port-forward shown in the prompt. Then put the
   printed refresh token into `YOUTUBE_REFRESH_TOKEN` (or keep the token file in
   `secrets/`).
4. Apply for the API **audit** (see above). Enable your channel's **advanced features**,
   which the Studio "Related video" step requires.

Quota: two uploads a week is far below the daily upload quota of a default API project.

### 7. Database, schedule, go

```bash
wwnn db migrate
wwnn db seed                                    # 7 SAMPLE archive items, clearly marked
wwnn archive import my_vetted_archive.csv       # your real, fact-checked items
sudo cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wwnn-orchestrator.service wwnn-weekly.timer wwnn-ingest.timer
docker compose up -d ollama bot
```
- **Sunday 09:00 Europe/Berlin:** `wwnn-weekly.timer` runs `wwnn week`. The selection
  closes after `WWNN_SELECTION_DEADLINE_HOURS` (30 h, with a reminder 6 h before),
  otherwise the week is skipped.
- `wwnn-orchestrator.service` (`wwnn loop`) advances runs. With `WWNN_STAGE_RUNNER=docker`,
  it launches `docker compose run --rm tts|longcat|compose` per stage. Data and assets
  are mounted at identical paths, so job files work everywhere. It also takes a GPU lock
  and unloads Ollama before each GPU stage.
- Cron alternative: [deploy/crontab.example](deploy/crontab.example).
- Want a test episode now? Send `/newrun` to the bot, or run `wwnn week`.

> **The SAMPLE archive items are illustrative placeholders, not fact-checked history.**
> They are flagged `is_sample=1` and labelled "SAMPLE" in Telegram. Replace them with your
> own vetted items before broadcasting anything.

---

## First GPU session: validate before trusting the schedule

The CPU dry run cannot exercise the three GPU stages. On the server, in this order:

1. **Chatterbox:** `docker compose run --rm tts python -c "from chatterbox.tts import ChatterboxTTS; ChatterboxTTS.from_pretrained('cuda')"`,
   then trigger a real run and listen to the two previews in Telegram. Tune
   `WWNN_*_EXAGGERATION` / `CFG_WEIGHT`, or switch `CHATTERBOX_MODEL=turbo`.
2. **LongCat smoke test:** approve a run, watch `data/runs/<week>/avatar/shots/*/longcat.log`
   and `nvidia-smi`. Check lip sync on the first shot. If you get an OOM: set
   `LONGCAT_OFFLOAD_KV_CACHE=on`, then try `offload`, lower `LONGCAT_MAX_SHOT_S`, or
   (24 GB) use `lowmem24`. Then **Resume** in Telegram. Finished shots are kept.
3. Note the per-shot `render_seconds` and adjust your expectations (and the GPU you rent).
4. Optional: `LONGCAT_RESOLUTION_ANNIKA=720p` for a sharper Short. A 9:16 crop of a 480p
   render is only 270×480 px before upscaling. It costs about 2.5–3× more GPU time for
   Annika's ~50 s.

## Configuration

Everything is in [.env.example](.env.example), commented and grouped by stage. A few
variables (`WWNN_MODELS_DIR`, `OLLAMA_IMAGE`, `LONGCAT_WITH_LOWMEM_PR`) are only read by
`docker-compose.yml`.

## Development

```bash
pip install -e ".[bot,upload,dev]"
ruff check wwnn tests && python -m pytest -q          # add  -m "not slow"  to skip the render test
```

## Known limitations

- The GPU stages (Chatterbox, LongCat) and live Telegram/YouTube/NewsData calls are
  covered by mocks in tests but **not yet run for real**. See "First GPU session".
- LongCat renders every shot from the reference image, so there can be a small pose jump
  at shot seams (shots ≤ 40 s are cut in speech pauses). Lower thirds help hide them.
- The Shorts "Related video" link is a manual Studio step, by YouTube's design.

## License and attribution

MIT. See [LICENSE](LICENSE), which keeps the MoneyPrinterTurbo copyright notice, and
[NOTICE.md](NOTICE.md) for third-party components. LongCat-Video and Chatterbox are MIT
and are installed at build time, not vendored. Check the licenses of the Ollama model
you choose and of your own assets.
