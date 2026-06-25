from pathlib import Path
from parser import PolicyParser

parser = PolicyParser()
DOCS = Path("../../docs")
pdfs = sorted([p for p in DOCS.rglob("*") if p.suffix.lower() == ".pdf"])

print(f"TOTAL PDFs: {len(pdfs)}\n")
for p in pdfs:
    rel = p.relative_to(DOCS)
    print("=" * 80)
    print(rel)
    try:
        r = parser.parse(p)
    except Exception as ex:
        print("  !! EXCEPCION:", repr(ex)); continue
    d, t, ri, fe = r["documento"], r["tomador"], r["riesgo"], r["fechas"]
    print(f"  compania : {d['compania']}   kind={d['kind']}")
    print(f"  nro      : {d['numero_poliza']}")
    print(f"  tomador  : {t['first_name']} | {t['last_name']}  doc={t['documento_numero']} ({t['documento_tipo']})")
    print(f"  patente  : {ri['patente']}   marca={ri['marca']} year={ri['year']} comb={ri['combustible']} uso={ri['uso']}")
    print(f"  fechas   : emi={fe['emision']} desde={fe['vigencia_desde']} hasta={fe['vigencia_hasta']}")
    print(f"  faltan   : {r['extraccion']['campos_no_extraidos']}")
