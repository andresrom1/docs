"""
parser.py v5 — convergencia.

Base estructural de v4 (contrato + identidad + validar-o-null) + clasificación de
tipo de documento y lectura de tarjetas de v3.1 + detección de compañía por CUIT
(arregla Sancor) + numero_poliza por patrón de compañía.

Principio rector: o el campo se extrae y VALIDA, o queda `null`. Nunca un valor dudoso.
Cada archivo aporta lo que tiene; el server une los documentos del mismo contrato por
`numero_poliza`.
"""
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

# CUIT del emisor → nombre canónico de la compañía. Clave fuerte y única de detección.
COMPANY_BY_CUIT = {
    "30500049460": "Sancor Seguros",
    "30500061711": "Río Uruguay",
    "30500000127": "Seguros Galicia",
    "30714590541": "Experta Seguros",
    "34500045339": "San Cristóbal",
}

# Aliases de texto para compañías sin CUIT conocido o como respaldo.
COMPANY_ALIASES = {
    "Sancor Seguros": ["SANCOR"],
    "Río Uruguay": ["RIO URUGUAY", "RIOURUGUAY"],
    "Seguros Galicia": ["GALICIA"],
    "Experta Seguros": ["EXPERTA"],
    "San Cristóbal": ["SAN CRISTOBAL", "SANCRISTOBAL"],
    "Mercantil Andina": ["MERCANTIL ANDINA", "MERCANTILANDINA"],
    "Triunfo Cooperativa de Seguros": ["TRIUNFO"],
}

COMPANY_CUITS = set(COMPANY_BY_CUIT.keys())

# Patente argentina: LLL999 (vieja), LL999LL (auto nueva), L999LLL (moto nueva).
PATENTE_RE = re.compile(r"^([A-Z]{3}\d{3}|[A-Z]{2}\d{3}[A-Z]{2}|[A-Z]\d{3}[A-Z]{3})$")


def _norm(text: str) -> str:
    """Mayúsculas sin acentos, para matching robusto."""
    return unicodedata.normalize("NFKD", text.upper()).encode("ASCII", "ignore").decode("ASCII")


class PolicyParser:
    def __init__(self, company_configs: Optional[List[Dict]] = None):
        # Se mantiene la firma para compatibilidad con main.py; v5 no usa anclas de config.
        self.company_configs = company_configs or []

    # ---------- pipeline ----------
    def parse(self, file_path: Path) -> Dict[str, Any]:
        raw_text = self._extract_text(file_path)
        if not raw_text or not raw_text.strip():
            return self._empty("pdf_sin_texto", file_path, None)

        company = self._detect_company(raw_text)
        if not company:
            return self._empty("compania_no_detectada", file_path, None)

        kind = self._detect_kind(raw_text, file_path)
        extracted = self._extract_for(company, raw_text)
        return self._build(extracted, company, kind, file_path)

    def _extract_text(self, file_path: Path) -> str:
        is_experta = "experta" in file_path.name.lower()
        parts: List[str] = []
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text(layout=is_experta) or ""
                    if t:
                        parts.append(t)
        except Exception:
            return ""
        return "\n".join(parts)

    # ---------- detección ----------
    def _detect_company(self, text: str) -> Optional[str]:
        # CUIT como token con límites (formateado o 11 dígitos contiguos), NO substring
        # de los dígitos concatenados — eso daba falsos positivos (Sancor en otra compañía).
        cuit_tokens = set(re.sub(r"\D", "", m) for m in re.findall(r"\b\d{2}-\d{8}-\d\b", text))
        cuit_tokens |= set(re.findall(r"\b\d{11}\b", text))
        for cuit, name in COMPANY_BY_CUIT.items():
            if cuit in cuit_tokens:
                return name
        # Sin CUIT: usar alias, pero si matchea MÁS de una compañía es ambiguo
        # (p. ej. la tarjeta verde Mercosur lista varias aseguradoras) → None a Pendientes.
        norm = _norm(text)
        matched = [name for name, aliases in COMPANY_ALIASES.items()
                   if any(a in norm for a in aliases)]
        return matched[0] if len(matched) == 1 else None

    def _detect_kind(self, text: str, file_path: Path) -> str:
        hay = _norm(text[:1500]) + " " + _norm(file_path.name)
        if any(k in hay for k in ["TARJETA DE CIRCULACION", "TARJETA CIRCULACION", "TARJETA_CIRCULACION", "TARJETA VERDE", "TARJETAVERDE", "TARJ. CIRC", "MERCOSUR"]):
            if "CERT" in hay:
                return "certificado"
            return "circulation-card"
        if "CERT" in hay:
            return "certificado"
        if any(k in hay for k in ["CUPON DE PAGO", "CUPON DE", "CUPONDE"]):
            return "cupon"
        return "poliza"

    # ---------- ruteo ----------
    def _extract_for(self, company: str, text: str) -> Dict[str, Optional[str]]:
        if company == "Sancor Seguros":
            return self._sancor(text)
        if company == "Río Uruguay":
            return self._rio_uruguay(text)
        if company == "Seguros Galicia":
            return self._galicia(text)
        if company == "San Cristóbal":
            return self._san_cristobal(text)
        if company == "Triunfo Cooperativa de Seguros":
            return self._triunfo(text)
        if company == "Mercantil Andina":
            return self._mercantil(text)
        if company == "Experta Seguros":
            return self._experta(text)
        return {}

    # ---------- extractores por compañía ----------
    def _sancor(self, text: str) -> Dict[str, Optional[str]]:
        e: Dict[str, Optional[str]] = {}
        e["numero_poliza"] = self._search(text, r"P[óo]liza\s*N[º°\.]?\s*:?\s*(\d{6,})")
        e["nombre_tomador"] = self._search(text, r"Asegurado:\s*([A-ZÁÉÍÓÚÑ ]+?)(?:\n|$)")
        e["documento_numero"] = self._first_valid_doc([self._search(text, r"DNI:\s*(\d[\d\.\-]{6,})")])
        e["patente"] = self._first_valid_patente([self._search(text, r"Dominio:\s*([A-Z0-9]+)")])
        e["year"] = self._search(text, r"Modelo:\s*((?:19|20)\d{2})")
        e["marca"] = self._search(text, r"\n([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]+?)\s*\n[^\n]*Dominio:")
        # Vigencia: línea con dos fechas "dd/mm/aaaa dd/mm/aaaa"
        m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})", text)
        if m:
            e["vigencia_desde"] = self._date(m.group(1))
            e["vigencia_hasta"] = self._date(m.group(2))
        return e

    def _rio_uruguay(self, text: str) -> Dict[str, Optional[str]]:
        e: Dict[str, Optional[str]] = {}
        e["numero_poliza"] = self._search(text, r"P[óo]liza:\s*([\d:]+\d)")
        e["nombre_tomador"] = self._search(text, r"Asegurado:\s*([A-ZÁÉÍÓÚÑ ]+?)(?:\n|Secci)")
        e["documento_numero"] = self._first_valid_doc([self._search(text, r"DNI/CUIL:\s*(\d{2}-\d{8}-\d)")])
        e["patente"] = self._first_valid_patente([self._search(text, r"Patente:\s*([A-Z0-9]+)")])
        e["marca"] = self._search(text, r"Marca y modelo:\s*([A-ZÁÉÍÓÚÑ0-9\. ]+?)\s*A[ñn]o:")
        e["year"] = self._search(text, r"A[ñn]o:\s*((?:19|20)\d{2})")
        e["combustible"] = self._search(text, r"Combustible:\s*([A-ZÁÉÍÓÚÑ]+)")
        e["uso"] = self._search(text, r"Uso:\s*([A-ZÁÉÍÓÚÑ]+)")
        e["vigencia_desde"] = self._date(self._search(text, r"Desde:\s*(\d{2}/\d{2}/\d{4})") or "")
        e["vigencia_hasta"] = self._date(self._search(text, r"Hasta:\s*(\d{2}/\d{2}/\d{4})") or "")
        return e

    def _galicia(self, text: str) -> Dict[str, Optional[str]]:
        e: Dict[str, Optional[str]] = {}
        e["numero_poliza"] = self._search(text, r"P[óo]liza\s*:?\s*(\d{8,})")
        e["nombre_tomador"] = self._search(text, r"Asegurado\s*:\s*([A-ZÁÉÍÓÚÑ ]+?)(?:\n|Entre|Domicilio)")
        e["patente"] = self._first_valid_patente([self._search(text, r"Dominio:\s*([A-Z0-9]+)"),
                                                  self._search(text, r"Patente\s+([A-Z0-9]+)")])
        e["year"] = self._search(text, r"A[ñn]o\s+((?:19|20)\d{2})")
        e["emision"] = self._date(self._search(text, r"Fecha de Emisi[óo]n:\s*\n?\s*(\d{2}/\d{2}/\d{4})") or "")
        return e

    def _san_cristobal(self, text: str) -> Dict[str, Optional[str]]:
        """Tabla densa: fila de etiquetas + fila de valores. Extracción posicional."""
        e: Dict[str, Optional[str]] = {}
        lines = text.split("\n")

        e["numero_poliza"] = self._search(text, r"(01-\d{2}-\d{2}-\d{6,})")

        for i, line in enumerate(lines):
            up = _norm(line)
            # Tomador: lo que precede a "AUTOMOTORES" en la fila de valores
            if "AUTOMOTORES" in up and not e.get("nombre_tomador"):
                head = line.split("AUTOMOTORES")[0].strip()
                # Solo tokens en MAYÚSCULAS (nombres); descarta frases legales en minúscula.
                toks = [t for t in head.split() if t.isalpha() and t.isupper() and len(t) > 1]
                if 2 <= len(toks) <= 4:
                    e["nombre_tomador"] = " ".join(toks)
                m = re.search(r"(\d{2}/\d{2}/\d{4})", line)
                if m:
                    e["vigencia_desde"] = self._date(m.group(1))
            # DNI del tomador (no el CUIT del emisor, que está arriba)
            if i > 4:
                m = re.search(r"D\.?N\.?I\.?\s*(\d{7,9})", up)
                if m and not e.get("documento_numero"):
                    e["documento_numero"] = self._first_valid_doc([m.group(1)])
            # Fila de riesgo: la línea siguiente a "RIESGO ... DOMINIO"
            if "RIESGO" in up and "DOMINIO" in up and i + 1 < len(lines):
                rl = lines[i + 1]
                toks = rl.split()
                for tok in reversed(toks):
                    p = self._valid_patente(tok)
                    if p:
                        e["patente"] = p
                        break
                ym = re.search(r"\b((?:19|20)\d{2})\b", rl)
                if ym:
                    e["year"] = ym.group(1)
                words = re.findall(r"[A-ZÁÉÍÓÚÑ]{3,}", _norm(rl))
                cand = [w for w in words if w not in ("FAMILIAR", "TIPO", "SEDAN", "PICK", "RURAL")]
                if cand:
                    e["marca"] = cand[0]
        # Vigencia hasta: primera fecha tras "VIGENCIA HASTA"
        e["vigencia_hasta"] = self._date(self._search(text, r"VIGENCIA HASTA[^\d]*(\d{2}/\d{2}/\d{4})") or "")
        return e

    def _triunfo(self, text: str) -> Dict[str, Optional[str]]:
        e: Dict[str, Optional[str]] = {}
        e["numero_poliza"] = self._search(text, r"N[úu]mero:\s*([\d\.]+)")
        if e.get("numero_poliza"):
            e["numero_poliza"] = re.sub(r"\D", "", e["numero_poliza"]) or None
        e["nombre_tomador"] = self._search(text, r"Nombre y Apellido:\s*([A-ZÁÉÍÓÚÑ ]+?)(?:\n|Endoso|Domicilio)")
        e["documento_numero"] = self._first_valid_doc([self._search(text, r"Doc\.?:\s*DNI\s*(\d{7,8})"),
                                                       self._search(text, r"\b(\d{2}-\d{8}-\d)\b")])
        e["patente"] = self._first_valid_patente([self._search(text, r"Patente:\s*([A-Z0-9]+)")])
        e["year"] = self._search(text, r"A[ñn]o:\s*((?:19|20)\d{2})")
        e["marca"] = self._search(text, r"Marca y Modelo:\s*([A-ZÁÉÍÓÚÑ0-9 ]+?)(?:\n|Cobertura)")
        e["uso"] = self._search(text, r"Uso del Veh[íi]culo:\s*([A-ZÁÉÍÓÚÑ]+)")
        # "desde las 12 hs. del28 -05 -2026 ... hasta ... del28 -05 -2027"
        ds = re.findall(r"del\s*(\d{1,2}\s*-\s*\d{1,2}\s*-\s*\d{4})", text)
        if len(ds) >= 1:
            e["vigencia_desde"] = self._date(ds[0])
        if len(ds) >= 2:
            e["vigencia_hasta"] = self._date(ds[1])
        return e

    def _mercantil(self, text: str) -> Dict[str, Optional[str]]:
        """Frente sin etiquetas: valores posicionales en el encabezado."""
        e: Dict[str, Optional[str]] = {}
        lines = [l.strip() for l in text.split("\n")]
        # numero: línea "016951262 000000"
        for line in lines:
            m = re.match(r"^(\d{9})\s+\d{6}$", line)
            if m:
                e["numero_poliza"] = m.group(1)
                break
        # fechas: línea "27.05.2026 27.06.2026" (punto separador)
        for line in lines:
            m = re.match(r"^(\d{2}\.\d{2}\.\d{4})\s+(\d{2}\.\d{2}\.\d{4})$", line)
            if m:
                e["vigencia_desde"] = self._date(m.group(1))
                e["vigencia_hasta"] = self._date(m.group(2))
                break
        # tomador: la línea de nombre que sigue a la línea de fechas (posicional).
        date_idx = next((i for i, l in enumerate(lines)
                         if re.match(r"^\d{2}\.\d{2}\.\d{4}\s+\d{2}\.\d{2}\.\d{4}$", l)), None)
        if date_idx is not None:
            for line in lines[date_idx + 1:date_idx + 5]:
                up = _norm(line)
                if (re.match(r"^[A-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ]+)+$", line)
                        and "AUTOMOTORES" not in up and "CONSUMIDOR" not in up
                        and 2 <= len(line.split()) <= 4):
                    e["nombre_tomador"] = line
                    break
        e["patente"] = self._first_valid_patente(re.findall(r"\b([A-Z]{2,3}\d{3}[A-Z]{0,3})\b", text))
        return e

    def _experta(self, text: str) -> Dict[str, Optional[str]]:
        """El frente suele venir ilegible; la tarjeta sí trae datos."""
        e: Dict[str, Optional[str]] = {}
        name = self._search(text, r"ASEGURADO\s*[:\n]\s*([A-ZÁÉÍÓÚÑ ]{6,}?)(?:\n|DOMICILIO)")
        if name and _norm(name) in {"DOMICILIO", "CONCEPTO", "VIGENCIA", "ASEGURADO"}:
            name = None
        e["nombre_tomador"] = name
        e["documento_numero"] = self._first_valid_doc([self._search(text, r"\b(\d{2}-\d{8}-\d)\b")])
        e["patente"] = self._first_valid_patente(re.findall(r"\b([A-Z]{2,3}\d{3}[A-Z]{0,3})\b", text))
        e["year"] = self._search(text, r"A[ñn]o\s*:?\s*((?:19|20)\d{2})")
        e["numero_poliza"] = self._search(text, r"(?:SOLICITUD|P[óo]liza)\s*N[º°]?\s*:?\s*(\d{6,})")
        m = re.search(r"(\d{2}[/-]\d{2}[/-]\d{4})", text)
        if m:
            e["vigencia_hasta"] = self._date(m.group(1))
        return e

    # ---------- helpers de extracción / validación ----------
    def _search(self, text: str, pattern: str) -> Optional[str]:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            return None
        val = m.group(1).strip()
        return val or None

    def _valid_patente(self, tok: Optional[str]) -> Optional[str]:
        if not tok:
            return None
        t = tok.strip().upper()
        return t if PATENTE_RE.match(t) else None

    def _first_valid_patente(self, candidates: List[Optional[str]]) -> Optional[str]:
        for c in candidates:
            p = self._valid_patente(c)
            if p:
                return p
        return None

    def _valid_doc(self, raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        d = re.sub(r"\D", "", raw)
        if len(d) in (8, 11) and d not in COMPANY_CUITS:
            return d
        return None

    def _first_valid_doc(self, candidates: List[Optional[str]]) -> Optional[str]:
        for c in candidates:
            d = self._valid_doc(c)
            if d:
                return d
        return None

    def _date(self, raw: str) -> Optional[str]:
        if not raw or not raw.strip():
            return None
        # rango "x al y" → tomar la segunda
        rng = re.search(r"(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\s*(?:al|a|AL|A)\s*(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})", raw)
        if rng:
            raw = rng.group(2)
        cleaned = re.sub(r"[^\d/\-\.]", "", raw)
        cleaned = cleaned.replace("-", "/").replace(".", "/")
        parts = cleaned.split("/")
        if len(parts) != 3:
            return None
        d, mth, y = parts
        if len(y) == 2:
            y = ("20" + y) if int(y) < 50 else ("19" + y)
        try:
            dt = datetime(int(y), int(mth), int(d))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None

    # ---------- armado del contrato ----------
    def _build(self, e: Dict[str, Optional[str]], company: str, kind: str, file_path: Path) -> Dict[str, Any]:
        doc = e.get("documento_numero") or ""
        tipo_persona = "juridica" if (len(doc) == 11 and doc[:2] in ("30", "33", "34")) else "fisica"
        first_name, last_name = self._split_name(e.get("nombre_tomador") or "")
        doc_tipo = "CUIT" if len(doc) == 11 else ("DNI" if len(doc) == 8 else "OTRO")

        all_fields = ["numero_poliza", "nombre_tomador", "documento_numero",
                      "patente", "marca", "modelo", "emision", "vigencia_hasta"]
        faltan = [f for f in all_fields if not e.get(f)]

        return {
            "schema_version": 1,
            "documento": {
                "kind": kind,
                "compania": company or None,
                "numero_poliza": e.get("numero_poliza"),
                "endoso_numero": None,
            },
            "tomador": {
                "tipo_persona": tipo_persona if doc else None,
                "first_name": first_name,
                "last_name": last_name,
                "razon_social": (e.get("nombre_tomador") if tipo_persona == "juridica" and doc else None),
                "documento_tipo": doc_tipo if doc else None,
                "documento_numero": doc or None,
            },
            "riesgo": {
                "tipo": "vehicle",
                "patente": e.get("patente"),
                "marca": e.get("marca"),
                "modelo": e.get("modelo"),
                "version": None,
                "year": e.get("year"),
                "combustible": e.get("combustible"),
                "uso": e.get("uso"),
                "codigo_postal": None,
            },
            "fechas": {
                "emision": e.get("emision"),
                "vigencia_desde": e.get("vigencia_desde"),
                "vigencia_hasta": e.get("vigencia_hasta"),
            },
            "archivo": {
                "nombre_original": file_path.name,
                "hash_sha256": None,
                "detectado_en": datetime.now().astimezone().isoformat(),
            },
            "extraccion": {
                "parser": "policy_parser_v5",
                "campos_no_extraidos": faltan,
            },
        }

    def _empty(self, reason: str, file_path: Path, company: Optional[str]) -> Dict[str, Any]:
        base = self._build({}, company or "", "otro", file_path)
        base["extraccion"]["razon"] = reason
        return base

    def _split_name(self, full: str) -> Tuple[Optional[str], Optional[str]]:
        full = full.strip()
        if not full:
            return None, None
        parts = full.split()
        if len(parts) == 1:
            return parts[0], None
        return " ".join(parts[:-1]), parts[-1]
