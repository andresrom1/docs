# Guía de uso — Ingestor Local de Pólizas (v5)

Instrucciones operativas para instalar, configurar, correr y automatizar el ingestor.
Para el *qué hace* y el *por qué* del parser, ver [README.md](README.md) (de esta carpeta)
y el README de la raíz del repo.

---

## 1. Qué hace, en una corrida

Cada vez que se ejecuta (`python main.py`), el ingestor:

1. **Escanea** los PDFs sueltos en la carpeta **Descargas** (`~/Downloads`).
2. **Filtra por antigüedad**: solo considera los **creados hace ≤ 90 días** (≈ 3 meses).
   Los más viejos se ignoran sin abrirlos.
3. **Evita reprocesar**: por hash SHA256 del contenido (`state.json`), saltea todo lo
   ya visto en corridas anteriores —tanto lo subido como lo descartado—.
4. **Parsea** cada PDF nuevo y detecta la compañía emisora.
5. **Filtra por naturaleza**: si el PDF **no es** una póliza de una aseguradora conocida
   (factura, resumen, ticket, etc.), **no lo sube**; lo registra como descartado.
6. **Sube** los que sí son pólizas (JSON + PDF) al endpoint del `workflow-assistant`.

> Todo degrada bien: lo que el parser no extrae con confianza igual sube el PDF crudo y
> cae en la cola de **Pendientes** del server. Nada se rompe; nada se sube con datos dudosos.

---

## 2. Requisitos

- **Python 3.9+** (probado en Windows 11).
- Dependencias: `pdfplumber`, `requests`, `pyyaml` (ver `requirements.txt`).

---

## 3. Instalación

Desde `app/v5/`:

```bash
# Crear y activar entorno virtual
python -m venv venv
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# Windows (cmd):
venv\Scripts\activate.bat
# Linux/Mac:
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt
```

---

## 4. Configuración (`config.yaml`)

Editar [config.yaml](config.yaml). Claves relevantes:

```yaml
watch:
  folder: "~/Downloads"   # carpeta Descargas del equipo
  recursive: false        # solo la raíz de Descargas, no subcarpetas
  pattern: "*.pdf"

endpoint:
  url: "https://tu-dominio.com/api/ingesta-local"
  token: "${SANCTUM_TOKEN}"   # se resuelve desde la variable de entorno
  timeout: 60
  max_retries: 3

output:
  state_file: "state.json"
  log_folder: "logs"
  log_level: "INFO"

rules:
  max_age_days: 90            # ventana de antigüedad (≈ 3 meses)
  keep_processed_for_days: 120  # retención del registro; debe ser > max_age_days
```

| Clave | Qué controla |
|---|---|
| `watch.folder` | Carpeta a vigilar. Default `~/Downloads` (la carpeta Descargas). |
| `watch.recursive` | Si `true`, también mira subcarpetas. Default `false`. |
| `watch.pattern` | Glob de archivos a tomar. Default `*.pdf`. |
| `rules.max_age_days` | Solo procesa archivos **creados** hace esta cantidad de días o menos. |
| `rules.keep_processed_for_days` | Cuánto se retiene cada registro en `state.json`. **Debe ser mayor** que `max_age_days`, si no un archivo aún dentro de la ventana se vuelve a parsear al vencer su registro. |
| `endpoint.token` | Token Sanctum. Recomendado dejar `${SANCTUM_TOKEN}` y exportar la variable. |

### Token por variable de entorno

```bash
# Windows (PowerShell):
$env:SANCTUM_TOKEN = "tu-token-sanctum"
# Linux/Mac:
export SANCTUM_TOKEN="tu-token-sanctum"
```

Si la variable no está definida y `config.yaml` la referencia, `main.py` aborta con un
error claro.

---

## 5. Uso manual

```bash
# Probar el parser contra el corpus de muestras (NO sube nada)
python _run_all.py

# Correr el ingestor real (escanea Descargas, parsea y sube)
python main.py
```

Al terminar imprime un resumen, por ejemplo:

```
=== Resumen === Subidos: 3 | Ya registrados: 12 | No-corpus: 5 | Errores: 0
```

| Contador | Significado |
|---|---|
| **Subidos** | Pólizas detectadas y enviadas OK al endpoint. |
| **Ya registrados** | Saltados por idempotencia (vistos en una corrida anterior). |
| **No-corpus** | PDFs que no son pólizas de aseguradoras conocidas; no se subieron. |
| **Errores** | Fallaron al parsear o al subir (quedan sin registrar; se reintentan la próxima). |

---

## 6. Automatización (1×/día)

### Windows — Task Scheduler

Crear una tarea básica que ejecute el Python del venv apuntando a `main.py`:

- **Programa/script**: `C:\Development\pas-mobile\ingestor\app\v5\venv\Scripts\python.exe`
- **Argumentos**: `main.py`
- **Iniciar en**: `C:\Development\pas-mobile\ingestor\app\v5`
- **Desencadenador**: diario, p. ej. 08:00.

> Definir `SANCTUM_TOKEN` como variable de entorno del **sistema** (o del usuario que
> corre la tarea), para que esté disponible sin sesión interactiva.

Equivalente por línea de comandos:

```powershell
schtasks /Create /SC DAILY /ST 08:00 /TN "IngestorPolizas" ^
  /TR "C:\Development\pas-mobile\ingestor\app\v5\venv\Scripts\python.exe C:\Development\pas-mobile\ingestor\app\v5\main.py"
```

### Linux/Mac — cron

```bash
0 8 * * * cd /ruta/al/ingestor/app/v5 && /ruta/al/venv/bin/python main.py >> logs/cron.log 2>&1
```

---

## 7. Registro de estado (`state.json`)

Lleva el control de lo ya procesado, indexado por **hash SHA256 del contenido** del PDF
(no por nombre: renombrar un archivo no lo hace reprocesar).

```json
{
  "version": 1,
  "processed": {
    "<sha256>": {
      "file_name": "Caratula Anual (5).pdf",
      "processed_at": "2026-06-24T08:00:12-03:00",
      "status": "uploaded"
    },
    "<sha256>": {
      "file_name": "factura_luz.pdf",
      "processed_at": "2026-06-24T08:00:13-03:00",
      "status": "skipped:compania_no_detectada"
    }
  }
}
```

| `status` | Significado |
|---|---|
| `uploaded` | Subido OK al endpoint. |
| `skipped:compania_no_detectada` | No es del corpus (sin aseguradora reconocida). |
| `skipped:pdf_sin_texto` | PDF sin texto extraíble (probable escaneo/imagen). |

Los registros con más de `keep_processed_for_days` días se purgan automáticamente al final
de cada corrida.

### Forzar el reprocesamiento de un archivo

Borrar su entrada de `state.json` (o el archivo entero para reprocesar todo). El próximo
`main.py` lo volverá a tomar si sigue dentro de la ventana de antigüedad.

---

## 8. Logs

Se escriben en `logs/ingestor_YYYYMMDD.log` (y también a stdout). El nivel se controla con
`output.log_level` (`INFO` por defecto; usar `DEBUG` para más detalle).

---

## 9. Resolución de problemas

| Síntoma | Causa probable / solución |
|---|---|
| `La carpeta no existe: ...` | `watch.folder` mal configurado o Descargas en otra ruta. |
| `Variable de entorno requerida no definida: SANCTUM_TOKEN` | Exportar `SANCTUM_TOKEN` antes de correr (ver §4). |
| Todos los PDFs salen "No-corpus" | El emisor no está en `COMPANY_BY_CUIT`/`COMPANY_ALIASES` de `parser.py`, o el PDF no tiene texto (necesita OCR). |
| Un PDF reciente no se procesa | Está fuera de la ventana `max_age_days`, ya está en `state.json`, o no matchea `watch.pattern`. |
| Falla la subida (`Errores`) | Endpoint/token/red. Revisar `endpoint.url` y conectividad; reintenta solo la próxima corrida. |

---

## 10. Agregar una aseguradora nueva

Resumen (detalle en [README.md](README.md) §"Cómo agregar una compañía"):

1. Agregar su CUIT a `COMPANY_BY_CUIT` (o un alias a `COMPANY_ALIASES`) en `parser.py`.
2. Escribir un extractor `_<compania>(text)` que devuelva los campos validados.
3. Engancharlo en `_extract_for`.
4. Probar con muestras reales vía `python _run_all.py`.
