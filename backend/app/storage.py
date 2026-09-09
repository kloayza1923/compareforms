"""Private immutable ZIP intake. No names from a ZIP become storage paths."""
from pathlib import Path, PurePosixPath
from hashlib import sha256
from uuid import uuid4
from collections import Counter
import re
import stat
import unicodedata
import zipfile
from pypdf import PdfReader

def name_key(name):
    text = re.sub(r"^\s*\d+\s*-\s*", "", Path(name).stem)
    text = re.sub(r"(?:[_ -]+(?:origen|modificado))$", "", text, flags=re.I)
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).casefold().split())

def patient_name(name):
    text = re.sub(r"^\s*\d+\s*-\s*", "", Path(name).stem).strip()
    return re.sub(r"(?:[_ -]+(?:origen|modificado))$", "", text, flags=re.I)

def private_path(root, key):
    root = Path(root).resolve()
    path = (root / key).resolve()
    if not path.is_relative_to(root) or path == root: raise ValueError("Ruta privada inválida.")
    return path

def ingest_zip(stream, folder: Path, settings):
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / f"upload-{uuid4()}.zip"
    count = 0
    with archive.open("xb") as out:
        while chunk := stream.read(1024*1024):
            count += len(chunk)
            if count > settings.max_upload_bytes: raise ValueError("ZIP excede el límite de carga.")
            out.write(chunk)
    documents, rejections = [], []
    try:
        with zipfile.ZipFile(archive) as z:
            entries = z.infolist()
            if len(entries) > settings.max_zip_entries: raise ValueError("Demasiados archivos en el ZIP.")
            if sum(i.file_size for i in entries) > settings.max_unpacked_bytes: raise ValueError("ZIP descomprimido excede el límite.")
            normalized = [unicodedata.normalize("NFKC", i.filename.replace("\\", "/")).casefold() for i in entries]
            duplicates = Counter(normalized)
            total = 0
            for info, normalized_name in zip(entries, normalized):
                if info.is_dir(): continue
                parts = PurePosixPath(normalized_name).parts
                reason = None
                if (not parts or normalized_name.startswith("/") or ".." in parts or ":" in normalized_name or "\x00" in normalized_name): reason = "Ruta insegura dentro del ZIP"
                elif stat.S_ISLNK(info.external_attr >> 16): reason = "Enlace simbólico no permitido"
                elif info.flag_bits & 1: reason = "Archivo cifrado no permitido"
                elif duplicates[normalized_name] > 1: reason = "Nombre duplicado después de normalizar"
                elif not normalized_name.endswith(".pdf"): reason = "Anexo no PDF: no se compara"
                elif info.file_size > settings.max_pdf_bytes: reason = "PDF excede el límite de tamaño"
                elif info.file_size / max(info.compress_size, 1) > 200: reason = "Ratio de compresión excesivo"
                if reason:
                    rejections.append({"name": info.filename, "reason": reason, "blocking": reason != "Anexo no PDF: no se compara"}); continue
                target = folder / f"{uuid4()}.pdf"
                digest = sha256(); size = 0
                try:
                    with z.open(info) as src, target.open("xb") as out:
                        while chunk := src.read(1024*1024):
                            size += len(chunk); total += len(chunk)
                            if size > settings.max_pdf_bytes or total > settings.max_unpacked_bytes:
                                raise ValueError("Límite excedido durante descompresión")
                            digest.update(chunk); out.write(chunk)
                    with target.open("rb") as file:
                        if not file.read(1024).lstrip().startswith(b"%PDF-"): raise ValueError("Contenido no PDF")
                    pdf = PdfReader(target)
                    if pdf.is_encrypted: raise ValueError("PDF cifrado")
                    if not 0 < len(pdf.pages) <= settings.max_pdf_pages: raise ValueError("Cantidad de páginas fuera de límite")
                    documents.append({"original_name": info.filename, "patient_name": patient_name(PurePosixPath(info.filename.replace("\\", "/")).name), "path": target, "size": size, "sha256": digest.hexdigest()})
                except Exception as exc:
                    # Partial intake remains private for traceability, never paired or served.
                    rejections.append({"name": info.filename, "reason": str(exc) if isinstance(exc, ValueError) else "PDF corrupto o no procesable"})
    except zipfile.BadZipFile as exc: raise ValueError("El archivo no es un ZIP válido.") from exc
    return documents, rejections
