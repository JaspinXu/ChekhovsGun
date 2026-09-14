"""Configuration: environment variables, optional TOML file, sane defaults.

Precedence (highest first):  explicit kwargs  >  env vars  >  config file  >  defaults.
Nothing here is required — ChekhovsGun runs with zero credentials using the
built-in local embedder; credentials only unlock the two source adapters.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

APP_NAME = "chekhovsgun"


def default_home() -> Path:
    """Where the index and config live. Override with CHEKHOVSGUN_HOME."""
    env = os.environ.get("CHEKHOVSGUN_HOME")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_DATA_HOME") or os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base).expanduser() / APP_NAME
    return Path.home() / f".{APP_NAME}"


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class YouTubeConfig:
    """YouTube Data API v3 access.

    ``api_key`` is enough for public/unlisted playlists. Personal collections
    (Watch Later ``WL``, Liked ``LL``) need an OAuth access token instead.
    """

    api_key: str = ""
    oauth_token: str = ""
    playlists: list[str] = field(default_factory=list)
    transcript_langs: list[str] = field(default_factory=lambda: ["zh-Hans", "zh-CN", "zh", "en"])

    @property
    def configured(self) -> bool:
        return bool(self.api_key or self.oauth_token)


@dataclass
class BilibiliConfig:
    """Bilibili web API access — driven entirely by browser cookies."""

    sessdata: str = ""
    bili_jct: str = ""
    dedeuserid: str = ""
    buvid3: str = ""
    folders: list[str] = field(default_factory=list)  # media_id list; empty = all
    include_seasons: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.sessdata)

    def cookie_header(self) -> str:
        parts = []
        if self.sessdata:
            parts.append(f"SESSDATA={self.sessdata}")
        if self.bili_jct:
            parts.append(f"bili_jct={self.bili_jct}")
        if self.dedeuserid:
            parts.append(f"DedeUserID={self.dedeuserid}")
        parts.append(f"buvid3={self.buvid3 or 'A1B2C3D4-0000-0000-0000-000000000000infoc'}")
        return "; ".join(parts)


@dataclass
class EmbeddingConfig:
    """Pluggable embedding backend.

    * ``local``  — dependency-free hashed n-gram vectors (default, works offline)
    * ``openai`` — any OpenAI-compatible endpoint (OpenAI, DashScope, SiliconFlow, Ollama…)
    * ``sentence-transformers`` — local neural model, if the package is installed
    """

    backend: str = "local"
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    dimensions: int = 512
    batch_size: int = 64


@dataclass
class LLMConfig:
    """Optional generator used to write the one-paragraph "why this matters"."""

    enabled: bool = True
    backend: str = "openai"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.3
    max_tokens: int = 400
    language: str = "auto"  # auto | zh | en

    @property
    def usable(self) -> bool:
        return self.enabled and bool(self.api_key)


@dataclass
class RetrievalConfig:
    chunk_chars: int = 420
    chunk_overlap_chars: int = 80
    chunk_max_seconds: float = 90.0
    top_k_chunks: int = 40
    top_k_items: int = 5
    dense_weight: float = 0.6
    lexical_weight: float = 0.4
    rrf_k: int = 60
    #: Minimum :attr:`~chekhovsgun.models.ItemHit.confidence` for a result to be
    #: returned at all. Raise it if the popup fires too eagerly.
    min_confidence: float = 0.30
    #: Secondary, relative cut against the best hit of this query.
    min_score_ratio: float = 0.45
    #: How many passages one saved item may contribute to the candidate list.
    max_chunks_per_item: int = 4
    exclude_same_video: bool = True


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8700
    cors_origins: list[str] = field(
        default_factory=lambda: [
            "https://www.youtube.com",
            "https://m.youtube.com",
            "https://www.bilibili.com",
            "https://m.bilibili.com",
            "https://t.bilibili.com",
        ]
    )
    allow_extension_origins: bool = True


@dataclass
class Config:
    home: Path = field(default_factory=default_home)
    db_path: Path | None = None
    youtube: YouTubeConfig = field(default_factory=YouTubeConfig)
    bilibili: BilibiliConfig = field(default_factory=BilibiliConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    request_timeout: float = 20.0
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )

    def __post_init__(self) -> None:
        self.home = Path(self.home).expanduser()
        if self.db_path is None:
            self.db_path = self.home / "index.db"
        else:
            self.db_path = Path(self.db_path).expanduser()

    # ------------------------------------------------------------------ IO --
    def ensure_home(self) -> Path:
        self.home.mkdir(parents=True, exist_ok=True)
        return self.home

    @property
    def config_file(self) -> Path:
        return self.home / "config.toml"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["home"] = str(self.home)
        data["db_path"] = str(self.db_path)
        return data

    def redacted(self) -> dict[str, Any]:
        """Same shape as :meth:`to_dict` but safe to show in the dashboard."""
        data = self.to_dict()
        for section, keys in (
            ("youtube", ("api_key", "oauth_token")),
            ("bilibili", ("sessdata", "bili_jct", "dedeuserid", "buvid3")),
            ("embedding", ("api_key",)),
            ("llm", ("api_key",)),
        ):
            for key in keys:
                if data[section].get(key):
                    data[section][key] = "***"
        return data


def _merge_file(cfg: Config, path: Path) -> None:
    if tomllib is None or not path.is_file():
        return
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:  # pragma: no cover - a broken file should not be fatal
        return
    for section_name, section in raw.items():
        target = getattr(cfg, section_name, None)
        if target is None or not isinstance(section, dict):
            continue
        for key, value in section.items():
            if hasattr(target, key):
                setattr(target, key, value)


def load_config(home: str | Path | None = None) -> Config:
    """Build a :class:`Config` from the config file then the environment."""
    cfg = Config(home=Path(home).expanduser() if home else default_home())
    _merge_file(cfg, cfg.config_file)

    yt = cfg.youtube
    yt.api_key = _env("CHEKHOVSGUN_YOUTUBE_API_KEY", "YOUTUBE_API_KEY", default=yt.api_key)
    yt.oauth_token = _env("CHEKHOVSGUN_YOUTUBE_OAUTH_TOKEN", default=yt.oauth_token)
    if playlists := _env("CHEKHOVSGUN_YOUTUBE_PLAYLISTS"):
        yt.playlists = [p.strip() for p in playlists.split(",") if p.strip()]

    bi = cfg.bilibili
    bi.sessdata = _env("CHEKHOVSGUN_BILIBILI_SESSDATA", "BILIBILI_SESSDATA", default=bi.sessdata)
    bi.bili_jct = _env("CHEKHOVSGUN_BILIBILI_JCT", "BILIBILI_JCT", default=bi.bili_jct)
    bi.dedeuserid = _env("CHEKHOVSGUN_BILIBILI_UID", "BILIBILI_UID", default=bi.dedeuserid)
    bi.buvid3 = _env("CHEKHOVSGUN_BILIBILI_BUVID3", default=bi.buvid3)
    if folders := _env("CHEKHOVSGUN_BILIBILI_FOLDERS"):
        bi.folders = [f.strip() for f in folders.split(",") if f.strip()]

    emb = cfg.embedding
    emb.backend = _env("CHEKHOVSGUN_EMBEDDING_BACKEND", default=emb.backend)
    emb.model = _env("CHEKHOVSGUN_EMBEDDING_MODEL", default=emb.model)
    emb.api_key = _env("CHEKHOVSGUN_EMBEDDING_API_KEY", "OPENAI_API_KEY", default=emb.api_key)
    emb.base_url = _env("CHEKHOVSGUN_EMBEDDING_BASE_URL", "OPENAI_BASE_URL", default=emb.base_url)
    emb.dimensions = _env_int("CHEKHOVSGUN_EMBEDDING_DIM", emb.dimensions)

    llm = cfg.llm
    llm.enabled = _env_bool("CHEKHOVSGUN_LLM_ENABLED", llm.enabled)
    llm.model = _env("CHEKHOVSGUN_LLM_MODEL", default=llm.model)
    llm.api_key = _env("CHEKHOVSGUN_LLM_API_KEY", "OPENAI_API_KEY", default=llm.api_key)
    llm.base_url = _env("CHEKHOVSGUN_LLM_BASE_URL", "OPENAI_BASE_URL", default=llm.base_url)
    llm.language = _env("CHEKHOVSGUN_LLM_LANGUAGE", default=llm.language)

    ret = cfg.retrieval
    ret.top_k_items = _env_int("CHEKHOVSGUN_TOP_K_ITEMS", ret.top_k_items)
    ret.min_confidence = _env_float("CHEKHOVSGUN_MIN_CONFIDENCE", ret.min_confidence)

    srv = cfg.server
    srv.host = _env("CHEKHOVSGUN_HOST", default=srv.host)
    srv.port = _env_int("CHEKHOVSGUN_PORT", srv.port)

    return cfg
