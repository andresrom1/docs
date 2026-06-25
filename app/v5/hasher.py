"""
hasher.py
Calcula SHA256 de archivos y maneja el registro de estado (idempotencia).
"""
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class StateManager:
    """Mantiene registro de archivos ya procesados por su hash de contenido."""

    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self._state = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            with open(self.state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"processed": {}, "version": 1}

    def _save(self):
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2, ensure_ascii=False)

    def compute_hash(self, file_path: Path) -> str:
        """SHA256 del contenido binario del archivo."""
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def is_processed(self, file_hash: str) -> bool:
        return file_hash in self._state["processed"]

    def mark_processed(self, file_hash: str, file_name: str, status: str = "uploaded"):
        self._state["processed"][file_hash] = {
            "file_name": file_name,
            "processed_at": datetime.now().isoformat(),
            "status": status
        }
        self._save()

    def cleanup_old(self, days: int = 30):
        """Elimina registros antiguos para no inflar el state.json."""
        cutoff = datetime.now() - timedelta(days=days)
        to_remove = [
            h for h, data in self._state["processed"].items()
            if datetime.fromisoformat(data["processed_at"]) < cutoff
        ]
        for h in to_remove:
            del self._state["processed"][h]
        if to_remove:
            self._save()
