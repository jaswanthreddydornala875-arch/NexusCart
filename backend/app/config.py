"""Application configuration."""
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{REPO_ROOT / 'backend' / 'db.sqlite3'}",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
