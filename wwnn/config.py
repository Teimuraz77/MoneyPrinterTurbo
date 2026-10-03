"""Central settings, read from environment variables (and an optional ``.env`` file).

Every knob that differs between a CPU dry-run box and the rented GPU server lives here,
so stages never read ``os.environ`` directly. See ``.env.example`` for documentation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_RSS_FEEDS = (
    "upi_odd|https://rss.upi.com/news/odd_news.rss",
    "npr_strange|https://feeds.npr.org/1146/rss.xml",
    "sky_strange|https://feeds.skynews.com/feeds/rss/strange.xml",
    "oddity_central|https://www.odditycentral.com/feed",
)

DEFAULT_TOM_PROMPT = (
    "A disillusioned, bored middle-aged male news anchor with tired eyes, short greying hair "
    "and a slightly loosened dark tie sits behind a glossy news desk in a dark emerald green "
    "news studio, soft green rim light, blurred monitor wall behind him. He is speaking to the "
    "camera in a flat, deadpan manner, minimal gestures, occasionally raising one eyebrow. "
    "Static medium shot, broadcast lighting, sharp focus."
)
DEFAULT_ANNIKA_PROMPT = (
    "A woman archivist with her hair in a tight bun, round reading glasses and a beige cardigan "
    "stands between tall wooden shelves of yellowed files and cardboard boxes in a dusty sepia "
    "archive room, warm dim tungsten light, dust particles floating in the air. She is speaking "
    "to the camera with a polite but passive-aggressive smile and small precise hand gestures. "
    "Static medium shot."
)


def load_dotenv(path: Path) -> None:
    """Minimal ``.env`` loader (KEY=VALUE, # comments). Existing env vars win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _bool(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # ---- paths -------------------------------------------------------------
    home: Path = REPO_ROOT
    data_dir: Path = REPO_ROOT / "data"
    db_path: Path = REPO_ROOT / "data" / "wwnn.db"
    assets_dir: Path = REPO_ROOT / "assets"
    fonts_dir: Path = REPO_ROOT / "resource" / "fonts"

    # ---- run mode ----------------------------------------------------------
    dry_run: bool = False                  # mocks for Ollama/TTS/LongCat/YouTube
    stage_runner: str = "local"            # local | docker  (GPU stages via `docker compose run`)
    compose_file: Path = REPO_ROOT / "docker-compose.yml"
    timezone: str = "Europe/Berlin"

    # ---- telegram ----------------------------------------------------------
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_allowed_user_ids: str = ""    # comma separated numeric ids
    telegram_in_dry_run: bool = False      # dry runs normally write to data/telegram_outbox.jsonl
    auto_approve: bool = False             # dry-run/testing only: auto-answer both Telegram gates
    selection_deadline_hours: float = 30.0
    approval_reminder_hours: float = 24.0

    # ---- sources -----------------------------------------------------------
    rss_feeds: str = ",".join(DEFAULT_RSS_FEEDS)   # "name|url,name|url"
    newsdata_api_key: str = ""
    newsdata_queries: str = "bizarre OR weird OR odd|absurd OR peculiar OR eccentric"
    newsdata_language: str = "en"
    proposal_live_count: int = 5
    proposal_archive_count: int = 3
    archive_cooldown_weeks: int = 26

    # ---- ollama ------------------------------------------------------------
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:32b-instruct"
    ollama_classifier_model: str = ""      # empty -> same as ollama_model
    ollama_temperature: float = 0.8
    ollama_timeout_s: float = 600.0
    ollama_use_classifier: bool = True

    # ---- pacing ------------------------------------------------------------
    video_a_min_s: float = 180.0
    video_a_max_s: float = 300.0
    annika_max_speech_s: float = 50.0      # Annika segment == Short, so it is capped
    short_max_s: float = 59.0
    cta_seconds: float = 3.5
    wpm_tom: float = 150.0
    wpm_annika: float = 155.0
    pacing_max_rounds: int = 3             # LLM rewrite rounds before TTS
    post_tts_max_rounds: int = 2           # re-script rounds after real TTS durations

    # ---- TTS (Chatterbox, English) -----------------------------------------
    chatterbox_model: str = "english"      # english | turbo
    tts_device: str = "cuda"
    tom_voice_ref: str = "assets/voices/tom_ref.wav"
    annika_voice_ref: str = "assets/voices/annika_ref.wav"
    tom_exaggeration: float = 0.30
    tom_cfg_weight: float = 0.55
    annika_exaggeration: float = 0.55
    annika_cfg_weight: float = 0.40
    tts_temperature: float = 0.8
    tts_seed_tom: int = 1701
    tts_seed_annika: int = 1887
    tts_sentence_pause_s: float = 0.40
    tts_segment_pause_s: float = 0.80
    tts_sample_rate: int = 48000

    # ---- LongCat-Video-Avatar 1.5 --------------------------------------------
    longcat_repo_dir: str = "/opt/LongCat-Video"
    longcat_checkpoint_dir: str = "/models/LongCat-Video-Avatar-1.5"
    longcat_model_type: str = "avatar-v1.5"
    longcat_stage_1: str = "ai2v"
    longcat_use_distill: bool = True
    longcat_use_int8: bool = True
    longcat_resolution: str = "480p"
    longcat_resolution_annika: str = ""    # optional override (e.g. 720p for a sharper 9:16 crop)
    longcat_vram_profile: str = "standard" # standard (>=40-48 GB) | offload | lowmem24 (PR #115)
    longcat_offload_kv_cache: str = "auto" # auto | on | off  (patched into the official script)
    longcat_skip_vocal_separation: bool = True
    longcat_ref_img_index: int = 10
    longcat_mask_frame_range: int = 3
    longcat_seed_tom: int = 4242
    longcat_seed_annika: int = 1887
    longcat_nproc: int = 1
    longcat_context_parallel: int = 1
    longcat_script: str = ""               # override entry script (relative to repo dir)
    longcat_extra_args: str = ""
    longcat_max_shot_s: float = 40.0
    longcat_shot_timeout_s: float = 4 * 3600
    tom_image: str = "assets/anchors/tom.png"
    annika_image: str = "assets/anchors/annika.png"
    tom_prompt: str = DEFAULT_TOM_PROMPT
    annika_prompt: str = DEFAULT_ANNIKA_PROMPT

    # ---- compositing ---------------------------------------------------------
    fps: int = 25
    video_a_width: int = 1920
    video_a_height: int = 1080
    short_width: int = 1080
    short_height: int = 1920
    short_crop_x: float = 0.5              # horizontal centre of the 9:16 crop (0..1)
    x264_preset: str = "medium"
    x264_crf: int = 20
    target_lufs: float = -14.0
    bgm_volume: float = 0.25
    subtitle_provider: str = "script"      # script (TTS sentence timings) | whisper (MPT subtitle.py)
    subtitle_font: str = "Be Vietnam Pro"
    mono_font_file: str = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
    sans_font_file: str = ""               # empty -> resource/fonts/BeVietnamPro-Bold.ttf
    vhs_osd_text: str = "PLAY"
    bumper_intro: str = "assets/bumpers/intro_16x9.mp4"
    bumper_transition: str = "assets/bumpers/archive_transition_16x9.mp4"
    bumper_outro: str = "assets/bumpers/outro_16x9.mp4"
    short_intro: str = ""                  # optional 9:16 bumper (counts against 60 s)
    lt_template_tom: str = "assets/lower_thirds/tom_template.png"
    lt_template_annika: str = "assets/lower_thirds/annika_template.png"
    bgm_news: str = "assets/bgm/news_bed.wav"
    bgm_archive: str = "assets/bgm/archive_bed.wav"

    # ---- YouTube -------------------------------------------------------------
    upload_enabled: bool = True
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_token_file: str = "secrets/youtube_token.json"
    youtube_category_id: str = "23"        # Comedy
    youtube_channel_url: str = ""

    extra: dict = field(default_factory=dict)

    # ------------------------------------------------------------------------
    @classmethod
    def from_env(cls, env_file: Path | None = None, **overrides) -> "Settings":
        load_dotenv(env_file or Path(os.environ.get("WWNN_ENV_FILE", REPO_ROOT / ".env")))
        kwargs: dict = {}
        for f in fields(cls):
            if f.name == "extra":
                continue
            key = f.name.upper() if f.name.split("_")[0] in {
                "telegram", "newsdata", "ollama", "longcat", "youtube", "chatterbox"
            } else "WWNN_" + f.name.upper()
            raw = os.environ.get(key)
            if raw is None:
                continue
            default = f.default
            if isinstance(default, bool):
                kwargs[f.name] = _bool(raw)
            elif isinstance(default, int):
                kwargs[f.name] = int(raw)
            elif isinstance(default, float):
                kwargs[f.name] = float(raw)
            elif isinstance(default, Path):
                kwargs[f.name] = Path(raw)
            else:
                kwargs[f.name] = raw
        kwargs.update(overrides)
        s = cls(**kwargs)
        # derived defaults: db/runs follow data_dir unless set explicitly
        if "db_path" not in kwargs and "data_dir" in kwargs:
            s.db_path = s.data_dir / "wwnn.db"
        return s

    # ---- helpers ---------------------------------------------------------------
    def path(self, p: str | Path) -> Path:
        """Resolve a possibly relative asset/secret path against ``home``."""
        p = Path(p)
        if p.is_absolute():
            return p
        if p.parts and p.parts[0] == "assets":           # assets may live outside the repo
            return self.assets_dir.joinpath(*p.parts[1:])
        return self.home / p

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def allowed_user_ids(self) -> set[int]:
        return {int(x) for x in self.telegram_allowed_user_ids.replace(" ", "").split(",") if x}

    @property
    def sans_font(self) -> Path:
        return Path(self.sans_font_file) if self.sans_font_file else self.fonts_dir / "BeVietnamPro-Bold.ttf"

    def feeds(self) -> list[tuple[str, str]]:
        out = []
        for item in self.rss_feeds.split(","):
            item = item.strip()
            if not item:
                continue
            name, _, url = item.partition("|")
            out.append((name.strip(), url.strip()) if url else (name.strip(), name.strip()))
        return out

    def anchor_resolution(self, anchor: str) -> str:
        if anchor == "annika" and self.longcat_resolution_annika:
            return self.longcat_resolution_annika
        return self.longcat_resolution
