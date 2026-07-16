from __future__ import annotations
import yaml
from pathlib import Path
from typing import Any
from pydantic import BaseModel


class AppConfig(BaseModel):
    name: str
    env: str
    data_dir: str
    forecasts_dir: str
    acknowledgements_dir: str
    cache_dir: str
    reports_dir: str
    logs_dir: str
    max_workers: int


class LoggingConfig(BaseModel):
    level: str
    file: str


class Config(BaseModel):
    app: AppConfig
    logging: LoggingConfig


def load_config(path: str | Path = "config.yaml") -> Config:
    """Load configuration from a YAML file."""
    # Resolve relative to this file's directory, not the CWD
    config_path = Path(__file__).resolve().parent / Path(path)
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(**raw) 
# Resolve relative to this file's directory, not the CWD
    config_path = Path(__file__).resolve().parent/Path
    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(**raw)


__all__ = ["load_config", "Config", "AppConfig", "LoggingConfig"]
