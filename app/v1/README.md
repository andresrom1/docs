# Ingestor Local de Pólizas

Vigila la carpeta `~/Downloads/polizas/`, extrae datos de PDFs de seguros y los envía al workflow-assistant.

## Instalación

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Configuración

1. Copiar `config.yaml` y ajustar:
   - `watch.folder`: ruta a la carpeta de pólizas
   - `endpoint.url`: URL del endpoint de ingesta
   - `endpoint.token`: token Sanctum (o dejar `${SANCTUM_TOKEN}` y exportar la variable)

2. Crear la subcarpeta de pólizas:
   ```bash
   mkdir ~/Downloads/polizas
   ```

## Uso

### Manual
```bash
python main.py
```

### Automático (cron - Linux/Mac)
```bash
# Editar crontab
crontab -e

# Agregar: ejecutar todos los días a las 8:00
0 8 * * * cd /ruta/al/ingestor && /ruta/al/venv/bin/python main.py >> logs/cron.log 2>&1
```

### Automático (Task Scheduler - Windows)
Crear tarea programada que ejecute `python main.py` una vez al día.

## Contrato JSON

El ingestor envía un JSON (campo `metadata`) + archivo PDF (campo `file`) vía multipart.
Shape acordado v1 con el server — ver `parser.py` método `_build_result()`.

## Idempotencia

El estado se guarda en `state.json` por hash SHA256 del contenido del archivo.
Un mismo PDF no se re-subirá nunca, aunque se renombre.

## Logs

En `logs/ingestor_YYYYMMDD.log`.
