"""
parser.py
Extracción determinística de datos de pólizas desde PDFs.
Sin LLM, sin costo. Usa pdfplumber + regex sobre anclas configuradas.
"""
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber


class PolicyParser:
    """Parser determinístico de pólizas de seguro."""

    def __init__(self, company_configs: List[Dict]):
        self.company_configs = company_configs

    def parse(self, file_path: Path) -> Dict[str, Any]:
        """
        Extrae texto del PDF e intenta parsear según las compañías configuradas.
        Si no reconoce la compañía, devuelve JSON con todo null + campos_no_extraidos completos.
        """
        raw_text = self._extract_text(file_path)

        if not raw_text or not raw_text.strip():
            # PDF escaneado sin capa de texto
            return self._build_empty_result("pdf_sin_texto", file_path)

        # Detectar compañía
        company_config = self._detect_company(raw_text)

        if not company_config:
            return self._build_empty_result("compania_no_detectada", file_path)

        # Extraer campos con anclas
        extracted = self._extract_fields(raw_text, company_config)

        # Normalizar y armar el JSON de salida
        return self._build_result(extracted, company_config, file_path)

    def _extract_text(self, file_path: Path) -> str:
        """Extrae todo el texto del PDF usando pdfplumber."""
        text_parts = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
        except Exception:
            return ""
        return "\n".join(text_parts)

    def _detect_company(self, text: str) -> Optional[Dict]:
        """Busca el nombre o alias de compañía en el texto."""
        text_upper = text.upper()
        for config in self.company_configs:
            for alias in config.get("aliases", []):
                if alias.upper() in text_upper:
                    return config
            if config.get("name", "").upper() in text_upper:
                return config
        return None

    def _extract_fields(self, text: str, config: Dict) -> Dict[str, Optional[str]]:
        """Extrae campos usando anclas de texto + regex."""
        anchors = config.get("anchors", {})
        date_format = config.get("date_format", "%d/%m/%Y")
        extracted = {}

        # Mapeo de anclas a campos
        field_map = {
            "policy_number": "numero_poliza",
            "holder_name": "nombre_tomador",
            "holder_doc": "documento_tomador",
            "vehicle_plate": "patente",
            "vehicle_brand": "marca",
            "vehicle_model": "modelo",
            "emission_date": "emision",
            "expiry_date": "vigencia_hasta",
        }

        for anchor_key, field_key in field_map.items():
            anchor_list = anchors.get(anchor_key, [])
            value = self._find_near_value(text, anchor_list)
            extracted[field_key] = value

        # Normalizar documento: quitar puntos y guiones
        if extracted.get("documento_tomador"):
            extracted["documento_tomador"] = re.sub(r"[.\-]", "", extracted["documento_tomador"])

        # Normalizar fechas a ISO
        for date_field in ["emision", "vigencia_hasta"]:
            if extracted.get(date_field):
                extracted[date_field] = self._normalize_date(
                    extracted[date_field], date_format
                )

        return extracted

    def _find_near_value(self, text: str, anchors: List[str]) -> Optional[str]:
        """
        Busca una ancla en el texto y extrae el valor que sigue.
        Estrategia: línea que contiene la ancla, luego regex para capturar valor.
        """
        lines = text.split("\n")
        for anchor in anchors:
            anchor_clean = anchor.strip().upper()
            for i, line in enumerate(lines):
                if anchor_clean in line.upper():
                    # Intentar extraer valor de la misma línea
                    value = self._extract_value_from_line(line, anchor)
                    if value:
                        return value.strip()
                    # Si no, mirar la siguiente línea
                    if i + 1 < len(lines):
                        next_val = lines[i + 1].strip()
                        if next_val and len(next_val) < 100:
                            return next_val
        return None

    def _extract_value_from_line(self, line: str, anchor: str) -> Optional[str]:
        """Extrae el valor después de la ancla en una línea."""
        # Patrones comunes: "Ancla: valor", "Ancla valor", "Ancla Nº valor"
        patterns = [
            re.escape(anchor) + r"[\s]*[:\s]+(.+)",
            re.escape(anchor) + r"[\s]+N[\s]*[º°]?[\s]*[:\s]*(.+)",
            re.escape(anchor) + r"[\s]+(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _normalize_date(self, date_str: str, fmt: str) -> Optional[str]:
        """Convierte fecha a ISO YYYY-MM-DD."""
        try:
            # Limpiar la string
            cleaned = re.sub(r"[^0-9/\-]", "", date_str.strip())
            dt = datetime.strptime(cleaned, fmt)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return None

    def _build_result(self, extracted: Dict, config: Dict, file_path: Path) -> Dict:
        """Arma el JSON final según el contrato acordado."""

        # Determinar tipo de persona
        doc_num = extracted.get("documento_tomador", "") or ""
        tipo_persona = "juridica" if len(doc_num) == 11 and doc_num.startswith(("30", "33", "34")) else "fisica"

        # Separar nombre
        nombre_completo = extracted.get("nombre_tomador", "") or ""
        first_name, last_name = self._split_name(nombre_completo)

        # Detectar tipo de documento
        doc_tipo = "CUIT" if len(doc_num) == 11 else ("DNI" if len(doc_num) == 8 else "OTRO")

        # Detectar tipo de documento (kind)
        text_upper = file_path.name.upper()
        kind = "otro"
        if "RENOV" in text_upper:
            kind = "poliza"  # renovación es póliza nueva
        elif "ENDOSO" in text_upper:
            kind = "endoso"
        elif "CERTIF" in text_upper:
            kind = "certificado"
        elif "CUPON" in text_upper or "PAGO" in text_upper:
            kind = "cupon"
        elif "CIRCULACION" in text_upper or "CIRCULACIÓN" in text_upper:
            kind = "circulation-card"
        else:
            kind = "poliza"  # default

        # Campos no extraídos
        all_fields = ["numero_poliza", "nombre_tomador", "documento_tomador", 
                      "patente", "marca", "modelo", "emision", "vigencia_hasta"]
        campos_no_extraidos = [f for f in all_fields if not extracted.get(f)]

        return {
            "schema_version": 1,
            "documento": {
                "kind": kind,
                "compania": config.get("name"),
                "numero_poliza": extracted.get("numero_poliza"),
                "endoso_numero": None
            },
            "tomador": {
                "tipo_persona": tipo_persona,
                "first_name": first_name,
                "last_name": last_name,
                "razon_social": nombre_completo if tipo_persona == "juridica" else None,
                "documento_tipo": doc_tipo,
                "documento_numero": doc_num if doc_num else None
            },
            "riesgo": {
                "tipo": "vehicle",
                "patente": extracted.get("patente"),
                "marca": extracted.get("marca"),
                "modelo": extracted.get("modelo"),
                "version": None,
                "year": None,
                "combustible": None,
                "uso": None,
                "codigo_postal": None
            },
            "fechas": {
                "emision": extracted.get("emision"),
                "vigencia_desde": None,
                "vigencia_hasta": extracted.get("vigencia_hasta")
            },
            "archivo": {
                "nombre_original": file_path.name,
                "hash_sha256": None,  # Se completa en hasher
                "detectado_en": datetime.now().isoformat()
            },
            "extraccion": {
                "parser": "policy_parser_v1",
                "campos_no_extraidos": campos_no_extraidos
            }
        }

    def _build_empty_result(self, reason: str, file_path: Path) -> Dict:
        """JSON para cuando no se pudo parsear nada."""
        return {
            "schema_version": 1,
            "documento": {
                "kind": "otro",
                "compania": None,
                "numero_poliza": None,
                "endoso_numero": None
            },
            "tomador": {
                "tipo_persona": None,
                "first_name": None,
                "last_name": None,
                "razon_social": None,
                "documento_tipo": None,
                "documento_numero": None
            },
            "riesgo": {
                "tipo": "vehicle",
                "patente": None,
                "marca": None,
                "modelo": None,
                "version": None,
                "year": None,
                "combustible": None,
                "uso": None,
                "codigo_postal": None
            },
            "fechas": {
                "emision": None,
                "vigencia_desde": None,
                "vigencia_hasta": None
            },
            "archivo": {
                "nombre_original": file_path.name,
                "hash_sha256": None,
                "detectado_en": datetime.now().isoformat()
            },
            "extraccion": {
                "parser": "policy_parser_v1",
                "campos_no_extraidos": [
                    "numero_poliza", "nombre_tomador", "documento_tomador",
                    "patente", "marca", "modelo", "emision", "vigencia_hasta",
                    "compania"
                ],
                "razon": reason
            }
        }

    def _split_name(self, full_name: str) -> Tuple[Optional[str], Optional[str]]:
        """Separa nombre completo en first_name + last_name."""
        if not full_name:
            return None, None
        parts = full_name.strip().split()
        if len(parts) == 1:
            return parts[0], None
        # Heurística simple: última palabra = apellido, resto = nombre
        return " ".join(parts[:-1]), parts[-1]
