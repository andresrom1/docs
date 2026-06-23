"""
scanner.py
Detecta PDFs nuevos en la carpeta vigilada.
"""
import fnmatch
from pathlib import Path
from typing import List


class Scanner:
    def __init__(self, folder: str, pattern: str = "*.pdf", recursive: bool = False):
        self.folder = Path(folder).expanduser().resolve()
        self.pattern = pattern
        self.recursive = recursive

    def scan(self) -> List[Path]:
        """Devuelve lista de PDFs encontrados, ordenados por fecha de modificación."""
        if not self.folder.exists():
            raise FileNotFoundError(f"La carpeta no existe: {self.folder}")

        files = []
        if self.recursive:
            for path in self.folder.rglob("*"):
                if path.is_file() and fnmatch.fnmatch(path.name, self.pattern):
                    files.append(path)
        else:
            for path in self.folder.iterdir():
                if path.is_file() and fnmatch.fnmatch(path.name, self.pattern):
                    files.append(path)

        # Ordenar por mtime (más antiguos primero, para procesar en orden de llegada)
        files.sort(key=lambda p: p.stat().st_mtime)
        return files
