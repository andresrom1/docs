# Ingestor local de documentos de póliza

Script Python local, **sin LLM, sin costo**, que corre 1×/día (cron / Task Scheduler).
Vigila una carpeta, detecta PDFs nuevos de pólizas, extrae datos de forma determinística
y los envía —**JSON + PDF**— a un endpoint de `workflow-assistant`, que da de alta lo que
falta y deja todo en una cola de **confirmación manual** (Pendientes).

> **Para el agente que continúa:** la única versión del parser es **`app/v5/`** (las
> iteraciones v1–v4 se borraron tras converger en v5). El lado servidor está documentado en
> `workflow-assistant/docs/v3/04-ingesta-local-documentos.md`.

---

## Por qué existe

El alta de pólizas que **no** pasaron por el flujo de WhatsApp (renovaciones, endosos,
pólizas viejas, cambios de compañía) hoy es carga manual del admin. Mucha de esa
documentación ya está en la PC del productor (carpeta de Descargas). Este ingestor
automatiza la **detección + subida + pre-llenado**, dejando la confirmación al humano.

Decisión de diseño central: **el parseo vive acá (local, gratis); el server NO re-extrae.**
Lo que el parser no saca con confianza igual sube el PDF crudo y cae en Pendientes
(degrada bien, nunca rompe).

---

## Arquitectura

```
main.py
  ├─ scanner.py    → detecta PDFs en Descargas, filtra por antigüedad (orden por mtime)
  ├─ hasher.py     → SHA256 del contenido + state.json (idempotencia)
  ├─ parser.py     → extracción determinística por compañía (pdfplumber)  ← el corazón
  └─ uploader.py   → multipart (JSON + PDF) al endpoint, con retry/backoff
```

Flujo por archivo (`main.py`):
1. `scanner.scan()` lista los PDFs de `~/Downloads` **creados hace ≤ `max_age_days`**
   (default 90 ≈ 3 meses); los más viejos ni se hashean.
2. `hash = sha256(archivo)`. Si ya está en `state.json` → saltar (idempotencia: cubre
   subidos y descartados previos).
3. `parser.parse(pdf)` → JSON del contrato (campos extraídos o `null`).
4. **Filtro de naturaleza**: si `documento.compania` es `null` (no es póliza de una
   aseguradora conocida) → no se sube; se marca `skipped:<razón>` en `state.json`.
5. Completar `archivo.hash_sha256` en el JSON.
6. `uploader.upload(json, pdf)` → multipart al endpoint. Si OK, marcar `uploaded` en `state.json`.

`state.json` se limpia de registros > `keep_processed_for_days` (default 120, > la ventana
de escaneo para que un archivo vigente no se re-parsee al vencer su registro).

---

## El parser (`app/v5/parser.py`)

Determinístico, **pdfplumber** (NO PyMuPDF/fitz — ver "Historia de versiones"). Pipeline:

1. **Extraer texto** (`layout=True` solo para Experta, que viene tabulado y roto).
2. **Detectar compañía** — por **CUIT del emisor** como token con límites (clave fuerte y
   única); fallback a alias de texto. **Si matchea más de una compañía por alias → `None`**
   (p. ej. la tarjeta verde Mercosur lista varias aseguradoras como representantes).
3. **Clasificar tipo (`kind`)** — por contenido del header + nombre de archivo:
   `poliza` · `certificado` · `circulation-card` · `cupon`.
4. **Rutear a un extractor por compañía** (función dedicada, no heurística genérica):
   `_sancor`, `_rio_uruguay`, `_galicia`, `_san_cristobal`, `_triunfo`, `_mercantil`, `_experta`.
5. **Armar el contrato** (ver abajo).

### Regla rectora: **validar-o-`null`** (nunca un valor dudoso)

En una cola de confirmación, un valor con-confianza-equivocado es **peor que vacío** (te lo
podés comer sin notarlo). Por eso cada campo se valida o queda `null`:

- **patente**: regex de formato argentino (`LLL999` vieja, `LL999LL` auto nueva, `L999LLL` moto).
- **documento** (DNI/CUIT): solo 8 u 11 dígitos, y **se excluye el CUIT del emisor**
  (`COMPANY_BY_CUIT`) para no confundirlo con el del cliente.
- **numero_poliza**: patrón específico por compañía (no "Prima"/"Endoso"/cualquier número suelto).
- **fechas**: deben parsear a fecha real; normaliza `/` `.` `-`, espacios y rangos "x al y".

### Cómo agregar una compañía

1. Si conocés su CUIT, agregalo a `COMPANY_BY_CUIT`. Si no, a `COMPANY_ALIASES`.
2. Escribí un `_<compania>(text)` que devuelva el dict de campos
   (`numero_poliza, nombre_tomador, documento_numero, patente, marca, year, combustible,
   uso, vigencia_desde, vigencia_hasta, emision`), usando `_search` + los validadores.
3. Engancharlo en `_extract_for`.
4. Probar con muestras reales (`_run_all.py`).

---

## El contrato JSON (shape v1)

Se envía como campo `metadata` (string JSON) + el PDF en el campo `file`, vía
`multipart/form-data`. Todo campo va siempre presente; `null` si no se extrajo.

```json
{
  "schema_version": 1,
  "documento": { "kind": "poliza", "compania": "Sancor Seguros",
                 "numero_poliza": "000031184413", "endoso_numero": null },
  "tomador":   { "tipo_persona": "fisica", "first_name": "SICOT LEONARDO",
                 "last_name": "FABIO", "razon_social": null,
                 "documento_tipo": "DNI", "documento_numero": "21407965" },
  "riesgo":    { "tipo": "vehicle", "patente": "AB235OR", "marca": null,
                 "modelo": null, "version": null, "year": "2017",
                 "combustible": null, "uso": null, "codigo_postal": null },
  "fechas":    { "emision": null, "vigencia_desde": "2026-02-19",
                 "vigencia_hasta": "2027-02-19" },
  "archivo":   { "nombre_original": "Caratula Anual (5).pdf",
                 "hash_sha256": "…", "detectado_en": "2026-06-24T08:00:00-03:00" },
  "extraccion":{ "parser": "policy_parser_v5",
                 "campos_no_extraidos": ["marca","modelo","emision"] }
}
```

- `kind` = enum `PolicyDocumentKind` exacto (no existe "renovacion": una renovación es una
  póliza nueva con `contrato_anterior_id` del lado server).
- `documento_numero` normalizado sin puntos/guiones. Fechas ISO `YYYY-MM-DD`.
- `archivo` siempre es el **PDF original tal cual** (byte por byte), parseable o no.

---

## Estado por compañía (corrida real sobre `docs/`, 15 PDFs)

| Compañía | compañía | nº | identidad | patente | fechas | Nota |
|---|---|---|---|---|---|---|
| **Sancor** | ✅ | ✅ | ✅ DNI | ✅ | ✅ | completo |
| **Río Uruguay** | ✅ | ✅ | ✅ CUIT | ✅ | ✅ | +combustible/uso |
| **San Cristóbal** | ✅ | ✅ | ✅ DNI | ✅ | desde✅ | tabla posicional |
| **Triunfo** | ✅ | ✅ | ✅ DNI | ✅ | ✅ | frente; tarjeta verde → ambigua → `None` |
| **Galicia** | ✅ | ✅ | — | ✅ | emisión✅ | sin doc del cliente en el PDF |
| **Mercantil** | ✅ | ✅ | — | tarjeta✅ | ✅ | frente sin patente (está en suplemento) |
| **Experta** | ✅ | — | — | ✅ | best-effort | frente con **texto roto → necesita OCR** |

**5 de 7 contratos** quedan con datos clave completos. Experta y Mercantil dependen de
Pendientes para completarse.

### Dato de dominio importante

La **patente suele estar en la tarjeta de circulación, no en el frente**. Cada archivo
aporta lo que tiene; **el server une los documentos del mismo contrato por `numero_poliza`,
con `patente` como fallback** (porque Experta no trae número y la tarjeta de Mercantil tampoco).

---

## Uso

```bash
# Instalar
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r app/v5/requirements.txt            # pdfplumber, requests, pyyaml

# Probar el parser contra el corpus de muestras (no sube nada)
cd app/v5 && python _run_all.py

# Correr el ingestor real (lee config.yaml: carpeta, endpoint, token)
cd app/v5 && python main.py
```

Automatizar: cron (`0 8 * * * …/python main.py`) o Task Scheduler de Windows, 1×/día.

`config.yaml` define `watch.folder` (default `~/Downloads`), `endpoint.url`,
`endpoint.token` (`${SANCTUM_TOKEN}`), `rules.max_age_days` (90) y
`rules.keep_processed_for_days` (120).

---

## Límites conocidos (caen a Pendientes, esperado)

1. **Experta** necesita **OCR** (el frente viene con texto ilegible/invertido). Hoy solo patente.
2. **Mercantil** frente no trae patente (está en suplemento no parseado); su tarjeta no trae número.
3. **Galicia/Mercantil** no traen el documento del cliente en estos PDFs.
4. `marca`/`modelo`/`emision` salen `null` seguido — no son load-bearing (la patente sí).

---

## Historia de versiones (por qué v5)

| v | Enfoque | Resultado |
|---|---|---|
| v1 | Esqueleto + parser ingenuo (línea + línea siguiente) | base; extracción pobre |
| v2 | Parser **por compañía** (pdfplumber) | corre en todas, pero bug del CUIT del emisor, detección frágil |
| v3 / v3.1 | **DeepSeek**: PyMuPDF + aplanar texto + regex genérica | **descartado** — regex greedy capturaba miles de chars de basura; 3/7 fallaban; schema ad-hoc |
| v4 | v2 + fixes (excluir CUIT emisor, corte de etiqueta, kind) | quitó el bug peligroso, pero **regresión: no detectaba Sancor** (marca en el pie) |
| **v5** | **Convergencia**: base v4 + clasificación y lectura de tarjetas (de v3.1) + detección por CUIT con límites + número por patrón + validar-o-null | **vigente** — 5/7 completos, sin basura, sin CUIT del emisor |

> Las versiones v1–v4 (y v3.1) y los scratch de iteración de la raíz se borraron el
> 2026-06-24 tras converger en v5. `app/v5/_run_all.py` queda como banco de pruebas.
