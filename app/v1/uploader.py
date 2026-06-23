"""
uploader.py
Envía JSON + archivo PDF al endpoint vía multipart/form-data.
"""
import json
import os
from pathlib import Path
from typing import Dict, Optional

import requests


class Uploader:
    def __init__(self, endpoint_url: str, token: str, timeout: int = 60, max_retries: int = 3):
        self.endpoint_url = endpoint_url
        self.token = token
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/json"
        })

    def upload(self, json_data: Dict, file_path: Path) -> Dict:
        """
        Envía multipart: campo 'metadata' con el JSON, campo 'file' con el PDF.
        Retorna la respuesta del server parseada.
        """
        # Preparar multipart
        metadata = json.dumps(json_data, ensure_ascii=False)

        files = {
            "file": (file_path.name, open(file_path, "rb"), "application/pdf"),
        }
        data = {
            "metadata": metadata
        }

        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.post(
                    self.endpoint_url,
                    data=data,
                    files=files,
                    timeout=self.timeout
                )
                response.raise_for_status()
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "response": response.json() if response.text else {}
                }
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                if attempt < self.max_retries:
                    import time
                    time.sleep(2 ** attempt)  # backoff exponencial
            finally:
                # Asegurar que el archivo se cierre
                files["file"][1].seek(0)

        return {
            "success": False,
            "error": last_error,
            "attempts": self.max_retries
        }
