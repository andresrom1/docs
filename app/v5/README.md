# Ingestor Local de Pólizas v3

Vigila la carpeta **Descargas** (`~/Downloads`), extrae datos de PDFs de 7 aseguradoras
argentinas y los envía al workflow-assistant.

Por corrida (1×/día) el ingestor:
1. **Escanea** los PDFs sueltos en `~/Downloads`.
2. **Filtra por antigüedad**: solo procesa los creados hace `max_age_days` o menos
   (≈ 3 meses); los más viejos se ignoran sin parsear.
3. **Idempotencia**: por hash SHA256 del contenido (`state.json`), no reprocesa lo ya visto.
4. **Filtro de naturaleza**: si no se detecta compañía conocida, el PDF **no es del
   corpus** (factura, resumen, etc.) → no se sube; se registra como descartado para no
   re-parsearlo en futuras corridas.

## Aseguradoras soportadas (calibradas)

| Compañía | Estrategia | Notas |
|---|---|---|
| **Sancor** | Texto libre | "Póliza N°:", "Asegurado:", "Dominio:" en líneas separadas |
| **San Cristóbal** | Tabla densa | Campos en posiciones fijas, extrae por patrón de línea |
| **Río Uruguay** | Formato mixto | "Póliza:", "Asegurado:", "Patente:" en líneas separadas |
| **Galicia** | Texto libre | "Póliza :", "Asegurado :", "Fecha de Emisión:" |
| **Mercantil Andina** | Texto libre | Fechas con punto como separador: "27.05.2026" |
| **Triunfo** | Texto libre particular | "Nombre y Apellido:", fechas con guiones "28 -05 -2026" |
| **Experta** | Tabla mal formada | Necesita `layout=True`, usa estrategia especial |

## Instalación

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuración

1. Editar `config.yaml`:
   - `watch.folder`: carpeta a vigilar (default `~/Downloads`)
   - `endpoint.url`: URL del endpoint de ingesta
   - `endpoint.token`: token Sanctum (o `${SANCTUM_TOKEN}` y exportar la variable)
   - `rules.max_age_days`: ventana de antigüedad en días (default `90` ≈ 3 meses)
   - `rules.keep_processed_for_days`: retención del registro (default `120`, debe ser
     mayor que `max_age_days`)

## Uso

### Manual
```bash
python main.py
```

### Automático (cron)
```bash
0 8 * * * cd /ruta/al/ingestor && /ruta/al/venv/bin/python main.py >> logs/cron.log 2>&1
```

## Cómo calibrar una nueva compañía

1. Correr el probe local:
   ```python
   import pdfplumber
   with pdfplumber.open("nueva.pdf") as pdf:
       print(pdf.pages[0].extract_text()[:2000])
   ```
2. Identificar las anclas (texto que precede a cada campo)
3. Agregar entrada en `config.yaml` con las anclas
4. Si el layout es especial (tabla densa, campos en posiciones fijas), agregar estrategia en `parser.py`

## Contrato JSON

El ingestor envía JSON (campo `metadata`) + PDF (campo `file`) vía multipart.
Shape acordado v1 con el server.

## Idempotencia y registro

Hash SHA256 del **contenido** del archivo, registrado en `state.json`. Se registran tanto
los **subidos** (`status: uploaded`) como los **descartados por no ser del corpus**
(`status: skipped:<razón>`), de modo que ninguno se reprocesa en la corrida siguiente.
Los registros con más de `keep_processed_for_days` días se purgan.

## Logs

En `logs/ingestor_YYYYMMDD.log`.
