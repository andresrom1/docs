"""
scanner.py
Detecta PDFs nuevos en la carpeta vigilada (por defecto, Descargas).

Filtra por antigüedad: solo devuelve archivos creados hace `max_age_days` o menos
(default 90 ≈ 3 meses). Los más viejos no se procesan (no se hashean ni parsean).
"""
import fnmatch
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional


def _creation_time(path: Path) -> float:
    """Fecha de creación del archivo, como timestamp.

    En Windows `st_ctime` es la fecha de creación. En plataformas que exponen
    `st_birthtime` (macOS, algunos *nix) se prefiere ese. En Linux clásico no hay
    fecha de creación real, así que cae a `st_ctime` (cambio de metadatos) como mejor
    aproximación disponible.
    """
    st = path.stat()
    return getattr(st, "st_birthtime", None) or st.st_ctime


class Scanner:
    def __init__(self, folder: str, pattern: str = "*.pdf", recursive: bool = False,
                 max_age_days: Optional[int] = None):
        self.folder = Path(folder).expanduser().resolve()
        self.pattern = pattern
        self.recursive = recursive
        self.max_age_days = max_age_days

    def scan(self) -> List[Path]:
        """Devuelve los PDFs de la carpeta, ordenados por fecha de modificación.

        Si `max_age_days` está definido, descarta los creados hace más de esa cantidad
        de días (no son candidatos a procesar).
        """
        if not self.folder.exists():
            raise FileNotFoundError(f"La carpeta no existe: {self.folder}")

        cutoff = None
        if self.max_age_days is not None:
            cutoff = (datetime.now() - timedelta(days=self.max_age_days)).timestamp()

        iterator = self.folder.rglob("*") if self.recursive else self.folder.iterdir()

        files = []
        for path in iterator:
            if not (path.is_file() and fnmatch.fnmatch(path.name, self.pattern)):
                continue
            if cutoff is not None and _creation_time(path) < cutoff:
                continue  # creado hace más de max_age_days → fuera de ventana
            files.append(path)

        # Ordenar por mtime (más antiguos primero, para procesar en orden de llegada)
        files.sort(key=lambda p: p.stat().st_mtime)
        return files
