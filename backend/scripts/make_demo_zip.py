"""Synthetic portal fixtures; no patient data. Run only as a development helper."""
from pathlib import Path
import io
import zipfile
import argparse
from reportlab.pdfgen import canvas

def main():
    p = argparse.ArgumentParser()
    p.add_argument("directory", type=Path)
    args = p.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    for side, price, name in (("original", "120,18", "PRUEBA PORTAL.pdf"), ("modified", "118,75", "1 - PRUEBA PORTAL.pdf")):
        stream = io.BytesIO()
        doc = canvas.Canvas(stream, invariant=1)
        cursor = doc.beginText(40, 740)
        cursor.setLeading(22)
        for line in ("DOCUMENTO SINTETICO - SIN DATOS PERSONALES", "Paciente de prueba: PRUEBA PORTAL", "Planilla de cargos para pruebas de software", "Prestacion administrativa ficticia sin valor clinico", f"Pinza de Biopsia Estandar 2.3mm ${price}", f"Total liquidacion ${price}"):
            cursor.textLine(line)
        doc.drawText(cursor)
        doc.showPage()
        doc.save()
        with zipfile.ZipFile(args.directory / f"{side}.zip", "x", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, stream.getvalue())
    print("Dos ZIP sintéticos creados para prueba de interfaz.")

if __name__ == "__main__": main()
