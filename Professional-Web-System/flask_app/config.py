"""Configuration for the Flask app."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get("SESSION_SECRET", "change-me-in-production-please-use-env")
    DATA_DIR = str(BASE_DIR / "data")
    DATABASE_PATH = str(BASE_DIR / "data" / "controlo_ponto.db")
    UPLOAD_DIR = str(BASE_DIR / "data" / "uploads")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8h

    # Face recognition
    FACE_TOLERANCE = 0.5  # lower = stricter
    MIN_FACE_SAMPLES = 3
    MAX_FACE_SAMPLES = 5

    # Attendance rules
    LATE_THRESHOLD_MINUTES = 5  # minutes after scheduled start counted as "late"
    HOURS_PER_FALTA = 8.0  # hours discounted per absence

    # Default seed admin (only created if no admin exists)
    DEFAULT_ADMIN_EMAIL = "admin@empresa.pt"
    DEFAULT_ADMIN_PASSWORD = "admin123"
    DEFAULT_ADMIN_NAME = "Administrador"
