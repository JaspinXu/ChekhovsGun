from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chekhovsgun.adapters.local import LocalFileAdapter
from chekhovsgun.config import Config
from chekhovsgun.engine import Engine

DEMO = Path(__file__).resolve().parents[1] / "chekhovsgun" / "data" / "demo.json"
DEMO_ITEMS = len(json.loads(DEMO.read_text(encoding="utf-8")))


@pytest.fixture
def config(tmp_path: Path) -> Config:
    cfg = Config(home=tmp_path / "home")
    cfg.ensure_home()
    return cfg


@pytest.fixture
def engine(config: Config) -> Engine:
    eng = Engine(config)
    yield eng
    eng.close()


@pytest.fixture
def seeded(engine: Engine) -> Engine:
    engine.ingest(LocalFileAdapter(engine.config, DEMO), force=True)
    return engine
