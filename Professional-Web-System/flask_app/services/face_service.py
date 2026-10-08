"""Face recognition utilities using face_recognition + OpenCV."""
from __future__ import annotations

import base64
import io
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image
import face_recognition

from flask import current_app

from ..db import get_db


def _decode_data_url(data_url: str) -> bytes:
    """Accept a `data:image/...;base64,xxx` URL or raw base64 and return bytes."""
    if not data_url:
        raise ValueError("Imagem em falta.")
    match = re.match(r"^data:image/[^;]+;base64,(.+)$", data_url)
    payload = match.group(1) if match else data_url
    return base64.b64decode(payload)


def load_image_from_data_url(data_url: str) -> np.ndarray:
    raw = _decode_data_url(data_url)
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    return np.array(img)


def compute_encoding(image_array: np.ndarray) -> Optional[np.ndarray]:
    """Return a single 128-d face encoding, or None if no face is detected."""
    locations = face_recognition.face_locations(image_array, model="hog")
    if not locations:
        return None
    # Use the largest face only
    locations.sort(key=lambda b: (b[2] - b[0]) * (b[1] - b[3]), reverse=True)
    encodings = face_recognition.face_encodings(image_array, [locations[0]])
    if not encodings:
        return None
    return encodings[0]


def compute_encoding_from_data_url(data_url: str) -> Optional[np.ndarray]:
    img = load_image_from_data_url(data_url)
    return compute_encoding(img)


def encoding_to_blob(enc: np.ndarray) -> bytes:
    return enc.astype(np.float64).tobytes()


def blob_to_encoding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float64)


def save_encoding(funcionario_id: int, encoding: np.ndarray) -> None:
    db = get_db()
    db.execute(
        "INSERT INTO face_encodings (funcionario_id, encoding) VALUES (?, ?)",
        (funcionario_id, encoding_to_blob(encoding)),
    )
    db.commit()


def list_encodings() -> List[Tuple[int, np.ndarray]]:
    db = get_db()
    rows = db.execute(
        "SELECT funcionario_id, encoding FROM face_encodings"
    ).fetchall()
    return [(r["funcionario_id"], blob_to_encoding(r["encoding"])) for r in rows]


def identify(data_url: str) -> Tuple[Optional[int], Optional[float]]:
    """Return (funcionario_id, distance) or (None, None) if not recognised."""
    image = load_image_from_data_url(data_url)
    enc = compute_encoding(image)
    if enc is None:
        return None, None

    candidates = list_encodings()
    if not candidates:
        return None, None

    # group by funcionario, take min distance per id
    distances: dict[int, float] = {}
    for fid, known in candidates:
        dist = float(np.linalg.norm(known - enc))
        if fid not in distances or dist < distances[fid]:
            distances[fid] = dist

    best_fid = min(distances, key=distances.get)
    best_dist = distances[best_fid]
    tolerance = current_app.config["FACE_TOLERANCE"]
    if best_dist <= tolerance:
        return best_fid, best_dist
    return None, best_dist


def save_snapshot(data_url: str, prefix: str = "snap") -> str:
    """Persist an image to disk for audit and return the relative path under data/uploads."""
    raw = _decode_data_url(data_url)
    upload_dir = Path(current_app.config["UPLOAD_DIR"])
    upload_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{prefix}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
    fpath = upload_dir / fname
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    img.save(fpath, "JPEG", quality=85)
    return fname
