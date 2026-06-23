#!/usr/bin/env python3
"""
main.py
Entry point del ingestor local.
Ejecutar 1x/día vía cron (Linux/Mac) o Task Scheduler (Windows).

Ejemplo cron (cada día a las 8:00):
  0 8 * * * cd /ruta/al/ingestor && /ruta/al/venv/bin/python main.py >> logs/cron.log 2>&1
"""
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml

from hasher import StateManager
from parser import PolicyParser
from scanner import Scanner
from uploader import Uploader


def setup_logging(log_folder: str, level: str = "INFO"):
    Path(log_folder).mkdir(parents=True, exist_ok=True)
    log_file = Path(log_folder) / f"ingestor_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger("ingestor")


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Resolver variables de entorno en strings
    def resolve_env(value):
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            var_name = value[2:-1]
            env_val = os.environ.get(var_name)
            if env_val is None:
                raise ValueError(f"Variable de entorno requerida no definida: {var_name}")
            return env_val
        return value

    # Aplicar a endpoint.token
    if "endpoint" in config and "token" in config["endpoint"]:
        config["endpoint"]["token"] = resolve_env(config["endpoint"]["token"])

    return config


def main():
    logger = setup_logging("logs", "INFO")
    logger.info("=== Ingestor Local iniciado ===")

    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Error cargando config: {e}")
        sys.exit(1)

    # Inicializar componentes
    scanner = Scanner(
        folder=config["watch"]["folder"],
        pattern=config["watch"].get("pattern", "*.pdf"),
        recursive=config["watch"].get("recursive", False)
    )

    state = StateManager(config["output"]["state_file"])
    parser = PolicyParser(config["parser"]["companies"])
    uploader = Uploader(
        endpoint_url=config["endpoint"]["url"],
        token=config["endpoint"]["token"],
        timeout=config["endpoint"].get("timeout", 60),
        max_retries=config["endpoint"].get("max_retries", 3)
    )

    # Escanear
    try:
        pdf_files = scanner.scan()
    except FileNotFoundError as e:
        logger.error(f"Carpeta de vigilancia no encontrada: {e}")
        sys.exit(1)

    logger.info(f"PDFs encontrados: {len(pdf_files)}")

    processed_count = 0
    skipped_count = 0
    error_count = 0

    for pdf_path in pdf_files:
        logger.info(f"Procesando: {pdf_path.name}")

        # 1. Calcular hash (idempotencia)
        file_hash = state.compute_hash(pdf_path)

        if state.is_processed(file_hash):
            logger.info(f"  → Ya procesado (hash: {file_hash[:16]}...), saltando.")
            skipped_count += 1
            continue

        # 2. Parsear
        try:
            json_data = parser.parse(pdf_path)
        except Exception as e:
            logger.error(f"  → Error parseando {pdf_path.name}: {e}")
            error_count += 1
            continue

        # 3. Completar hash en el JSON
        json_data["archivo"]["hash_sha256"] = file_hash

        # 4. Subir
        try:
            result = uploader.upload(json_data, pdf_path)
            if result["success"]:
                logger.info(f"  → Subido OK. Server response: {result.get('response', {})}")
                state.mark_processed(file_hash, pdf_path.name, "uploaded")
                processed_count += 1
            else:
                logger.error(f"  → Fallo subida después de {result['attempts']} intentos: {result['error']}")
                error_count += 1
        except Exception as e:
            logger.error(f"  → Error inesperado en upload: {e}")
            error_count += 1

    # Cleanup de state antiguo
    keep_days = config["rules"].get("keep_processed_for_days", 30)
    state.cleanup_old(keep_days)

    logger.info(f"=== Resumen === Procesados: {processed_count} | Saltados: {skipped_count} | Errores: {error_count}")
    logger.info("=== Ingestor Local finalizado ===")


if __name__ == "__main__":
    main()
