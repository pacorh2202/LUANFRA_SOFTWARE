"""Uso: python scripts/diagnosticar_ordenes.py /ruta/privada/export.csv"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.servicios.importacion_ordenes import diagnosticar

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    resultado = diagnosticar(args.csv)
    # No mostrar nombres, descripciones, costes ni otros datos empresariales.
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
