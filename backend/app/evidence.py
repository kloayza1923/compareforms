"""Render a private PDF page and locate persisted finding text without modifying the PDF."""
from contextlib import closing
import base64
import ctypes
import io
import math
import threading
import unicodedata
import pypdfium2 as pdfium
from PIL import Image, ImageDraw

_RENDER_LOCK = threading.Lock()  # PDFium is not thread-safe within one process.
MAX_CHARACTERS = 200_000

def compact(text):
    return ''.join(c for c in unicodedata.normalize('NFD', text.casefold()) if not c.isspace() and unicodedata.category(c) != 'Mn')

def match_indices(haystack, evidence):
    target = compact(evidence)
    if not target or len(target) > MAX_CHARACTERS:
        return []
    start = haystack.find(target)
    if start >= 0 and haystack.find(target, start + 1) < 0:
        return [(start, start + len(target))]
    # Full extracted blocks may wrap differently. Only highlight unique exact lines.
    spans = []
    for line in evidence.splitlines():
        target = compact(line)
        if len(target) < 8:
            continue
        start = haystack.find(target)
        if start >= 0 and haystack.find(target, start + 1) < 0:
            spans.append((start, start + len(target)))
    return spans

def merge_boxes(boxes):
    rows = []
    for left, top, right, bottom in sorted(boxes, key=lambda b: (round(b[1] / 4), b[0])):
        if right <= left or bottom <= top:
            continue
        row = next((r for r in reversed(rows[-8:]) if abs(r[1] - top) <= 4 and abs(r[3] - bottom) <= 5 and left <= r[2] + 28 and right >= r[0] - 3), None)
        if row:
            row[0] = min(row[0], left); row[1] = min(row[1], top)
            row[2] = max(row[2], right); row[3] = max(row[3], bottom)
        else:
            rows.append([left, top, right, bottom])
    return rows

def render_evidence(path, page_number, evidence, *, ocr_enabled=True):
    with _RENDER_LOCK, closing(pdfium.PdfDocument(str(path))) as doc:
        if not 1 <= page_number <= len(doc):
            raise ValueError('Página fuera del documento')
        with closing(doc[page_number - 1]) as page:
            width, height = page.get_size()
            if not all(math.isfinite(v) and 0 < v <= 8000 for v in (width, height)):
                raise ValueError('Dimensiones de página no admitidas')
            scale = min(2.0, 1600 / width, 2000 / height)
            with closing(page.render(scale=scale)) as bitmap:
                image = bitmap.to_pil().convert('RGB')
                boxes = []
                with closing(page.get_textpage()) as textpage:
                    if textpage.count_chars() > MAX_CHARACTERS:
                        image.close(); raise ValueError('Texto de página fuera del límite')
                    chars, indices = [], []
                    for i in range(textpage.count_chars()):
                        value = pdfium.raw.FPDFText_GetUnicode(textpage, i)
                        char = compact(chr(value)) if value else ''
                        chars.append(char); indices.extend([i] * len(char))
                    text = ''.join(chars)
                    chosen = {indices[k] for start, end in match_indices(text, evidence) for k in range(start, end)}
                    def position(x, y):
                        bx, by = ctypes.c_int(), ctypes.c_int()
                        ok = pdfium.raw.FPDF_PageToDevice(page, 0, 0, bitmap.width, bitmap.height, 0, x, y, ctypes.byref(bx), ctypes.byref(by))
                        if not ok: raise ValueError('No se pudo localizar la región')
                        return bx.value, by.value
                    for i in sorted(chosen):
                        left, bottom, right, top = textpage.get_charbox(i)
                        x1, y1 = position(left, top); x2, y2 = position(right, bottom)
                        boxes.append((min(x1,x2),min(y1,y2),max(x1,x2),max(y1,y2)))
                method = 'text'
                if not boxes and evidence.strip() and ocr_enabled:
                    import pytesseract
                    languages = set(pytesseract.get_languages(config=''))
                    lang = '+'.join(x for x in ('spa','eng') if x in languages)
                    if lang:
                        try:
                            data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT, timeout=20)
                            chars, indices = [], []
                            for i, word in enumerate(data['text']):
                                value = compact(word) if float(data['conf'][i]) >= 60 else ''
                                chars.append(value); indices.extend([i] * len(value))
                            chosen = {indices[k] for start,end in match_indices(''.join(chars), evidence) for k in range(start,end)}
                            boxes = [(data['left'][i],data['top'][i],data['left'][i]+data['width'][i],data['top'][i]+data['height'][i]) for i in chosen]
                            method = 'ocr'
                        except (RuntimeError, pytesseract.TesseractError):
                            pass
                boxes = merge_boxes(boxes)
                # Multiply keeps text black while the white background becomes yellow.
                if boxes:
                    from PIL import ImageChops
                    overlay = Image.new('RGB', image.size, 'white'); draw = ImageDraw.Draw(overlay)
                    for left,top,right,bottom in boxes:
                        draw.rectangle((max(0,left-2),max(0,top-2),min(image.width,right+2),min(image.height,bottom+2)),fill=(255,235,70))
                    highlighted = ImageChops.multiply(image,overlay); image.close();overlay.close();image=highlighted
                out=io.BytesIO();image.save(out,format='PNG');image.close()
                return {'page':page_number,'image':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode(),
                        'highlighted':bool(boxes),'regions':boxes,'method':method if boxes else None}
