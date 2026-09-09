from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas

from app.comparison import Page, _align_pages, _document_type, _line_changes, _money_value, _readable, compare_documents


def pdf(path: Path, pages: list[str]):
    doc = canvas.Canvas(str(path), invariant=1)
    for text in pages:
        cursor = doc.beginText(40, 770)
        for line in text.splitlines():
            cursor.textLine(line)
        doc.drawText(cursor)
        doc.showPage()
    doc.save()
    return path


def page(number, text):
    return Page(number, text)


def test_global_reordering_has_no_added_or_removed():
    originals = [page(1, "Consentimiento informado procedimiento endoscopia autorizacion paciente acepta biopsia"),
                 page(2, "Epicrisis enfermedad polipo colon diagnostico evolucion favorable egreso clinico"),
                 page(3, "Factura proveedor materiales pinza jeringa numero autorizacion fiscal")]
    modified = [page(i + 1, originals[n].text) for i, n in enumerate([2, 0, 1])]
    rows = _align_pages(originals, modified)
    assert {(x["page_original"], x["page_modified"]) for x in rows} == {(1, 2), (2, 3), (3, 1)}
    assert all(x["relocated"] for x in rows)
    assert all(x["status"] not in {"added", "removed"} for x in rows)


def test_shift_after_insertion_is_not_relocation():
    a = [page(1, "Texto identificador uno contenido medico bastante extenso original"), page(2, "Resumen historia dos tratamiento final alta hospitalaria")]
    b = [page(1, "Factura proveedor ajeno totalmente distinto soporte mercantil"), page(2, a[0].text), page(3, a[1].text)]
    rows = _align_pages(a, b)
    assert sum(x["status"] == "added" for x in rows) == 1
    assert not any(x.get("relocated") for x in rows)


def test_unrelated_pages_are_not_forced_together():
    rows = _align_pages([page(1, "Historia resumen antecedentes anestesia evolucion diagnostico clinico")], [page(1, "Comprobante tributario proveedor direccion sucursal subtotal impuesto factura")])
    assert {x["status"] for x in rows} == {"added", "removed"}
    assert len(rows) == 2
    assert all(x["review_required"] for x in rows)


def test_money_preserves_decimal_and_before_after_pages():
    a = page(4, "Planilla de cargos del proveedor\nPinza de Biopsia Estandar 2.3mm $120,18\nTotal liquidacion $841,74")
    b = page(9, "Planilla de cargos del proveedor\nPinza de Biopsia Estandar 2.3mm $118,75\nTotal liquidacion $839,87")
    # Adjacent changes may form a multi-line block; do not guess row positions.
    f = _line_changes(page(4, a.text.splitlines()[1]), page(9, b.text.splitlines()[1]))[0]
    assert f["change_type"] == "modified"
    assert f["page_original"] == 4 and f["page_modified"] == 9
    amount = f["monetary_changes"][0]
    assert Decimal(amount["delta"]) == Decimal("-1.43")
    assert f["before"].endswith("$120,18") and f["after"].endswith("$118,75")


def test_ocr_never_becomes_confirmed_money():
    a = Page(1, "Pinza de Biopsia Estandar $120,18", source="ocr", confidence=0.95)
    b = Page(2, "Pinza de Biopsia Estandar $118,75", source="ocr", confidence=0.95)
    finding = _line_changes(a, b)[0]
    assert finding["monetary_changes"] == []
    assert finding["review_required"] is True


def test_money_without_legible_context_is_not_confirmed():
    finding = _line_changes(page(1, "dfr $308"), page(1, "dfr $310"))[0]
    assert finding["monetary_changes"] == []


def test_adjacent_price_and_liquidation_changes_are_both_detected():
    a = page(1, "Planilla de cargos del proveedor\nPinza de Biopsia Estandar $120,18\nTotal liquidacion $841,74")
    b = page(1, "Planilla de cargos del proveedor\nPinza de Biopsia Estandar $118,75\nTotal liquidacion $839,87")
    findings = _line_changes(a, b)
    amounts = [m for f in findings for m in f.get("monetary_changes", [])]
    assert [Decimal(m["delta"]) for m in amounts] == [Decimal("-1.43"), Decimal("-1.87")]


def test_line_removed_retains_modified_corresponding_page():
    a = page(4, "Cabecera documental\nTexto que desaparece\nContenido que permanece")
    b = page(9, "Cabecera documental\nContenido que permanece")
    finding = _line_changes(a, b)[0]
    assert finding["change_type"] == "removed"
    assert (finding["page_original"], finding["page_modified"]) == (4, 9)
    assert finding["before"] == "Texto que desaparece" and finding["after"] == ""


def test_money_parser_abstains_on_ambiguous_separators():
    assert _money_value("1,234") is None
    assert _money_value("1.234,56") == Decimal("1234.56")
    assert _money_value("14,2500") == Decimal("14.2500")
    assert _money_value("14.25.00") is None


def test_duplicate_near_candidates_are_marked_for_review():
    a = [page(1, "Historia clinica paciente diagnostico enfermedad evolucion favorable fecha 2025")]
    b = [page(1, a[0].text), page(2, a[0].text)]
    rows = _align_pages(a, b)
    matched = next(x for x in rows if x["page_original"] is not None)
    assert matched["review_required"] is True
    assert len({x["page_modified"] for x in rows if x["page_modified"]}) == 2


def test_identical_pdf(tmp_path):
    a = pdf(tmp_path / "a.pdf", ["Historia clinica completa paciente de prueba sin datos reales"])
    result = compare_documents(a, a)
    assert result["status"] == "no_differences_detected"
    assert result["pages_original"] == 1 and result["priority"] == 0


def test_metadata_change_not_medical_change(tmp_path):
    a = pdf(tmp_path / "a.pdf", ["Historia clinica completa paciente de prueba sin datos reales"])
    b = tmp_path / "b.pdf"
    writer = PdfWriter(clone_from=str(a))
    writer.add_metadata({"/Subject": "Only metadata changes"})
    with b.open("wb") as handle:
        writer.write(handle)
    result = compare_documents(a, b, ocr_enabled=False)
    assert result["hash_original"] != result["hash_modified"]
    assert result["status"] == "no_differences_detected"
    assert result["findings"] == []


def test_unreadable_page_does_not_report_no_differences(tmp_path):
    a = pdf(tmp_path / "a.pdf", ["x"])
    b = pdf(tmp_path / "b.pdf", ["y"])
    result = compare_documents(a, b, ocr_enabled=False)
    assert result["status"] == "inconclusive"
    assert result["limitations"]
    assert result["priority"] is None


def test_30_to_50_can_reconcile_22_added_two_removed(monkeypatch, tmp_path):
    # Unique synthetic pages, no patient information and no asserted real map.
    import app.comparison as module
    texts = [f"Documento unico {i} " + (f"token{i} " * 10) for i in range(52)]
    a = [Page(i + 1, texts[i], visual_hash=f"hash-{i}") for i in range(30)]
    indices = list(range(28)) + list(range(30, 52))
    b = [Page(i + 1, texts[j], visual_hash=f"hash-{j}") for i, j in enumerate(indices)]
    # Explicit distinct feature sets keep the dummy-node test about cardinality.
    monkeypatch.setattr(module, "_similarity", lambda x, y, weights: 1.0 if x.visual_hash == y.visual_hash else 0)
    rows = _align_pages(a, b)
    assert sum(x["status"] == "added" for x in rows) == 22
    assert sum(x["status"] == "removed" for x in rows) == 2


def test_page_limit_is_explicit_not_truncated(monkeypatch, tmp_path):
    import app.comparison as module
    monkeypatch.setattr(module, "MAX_PAGES", 1)
    a = pdf(tmp_path / "a.pdf", ["Texto documental primero paciente ficticio", "Texto documental segundo paciente ficticio"])
    b = pdf(tmp_path / "b.pdf", ["Texto documental distinto paciente ficticio"])
    result = compare_documents(a, b)
    assert result["status"] == "inconclusive"
    assert not result["page_counts_reconciled"]
    assert result["pages_original"] == 2
    assert result["limitations"]


def test_gibberish_not_readable():
    assert not _readable("$308 x drf hkj ttt ppz bbb")
    assert _readable("Pinza de biopsia estandar esteril descartable")


def test_symbol_flooding_text_layer_requires_ocr():
    assert not _readable("a'ar(c,O£:,aF#c|`aLO]`.i+-f{g`n(e)d6dtfT]RE[fRis;f`£}.£lviEea(/I:%T;¥iE[J:/(DH05n;O£:#=Ofo^i2£cgE" * 5)
    assert not _readable("iiigi5ioiii ? `.. 89! aa= I ziiii i;iR!;!!i i!5! iii 8i!!! 8!ii iii! !i :... S :.i I ii i8 fi,= i Lc i+=5FE i")
    assert _readable("Total liquidacion del paciente $841,74. Pinza de biopsia: USD 120,18; estéril, descartable.")


def test_medical_document_type_precedes_invoice_reference():
    assert _document_type("INFORME TÉCNICO MÉDICO para justificación de prestaciones adicionales. Se adjunta factura del proveedor.") == "Informe técnico-médico"


def test_unmatched_pages_are_review_candidates_not_confirmed_additions(tmp_path):
    a = pdf(tmp_path / "a.pdf", ["Historia clinica paciente tratamiento hospitalario cirugia diagnostico"])
    b = pdf(tmp_path / "b.pdf", ["Factura numero establecimiento proveedor tributario subtotal tarifa mercantil"])
    result = compare_documents(a, b, ocr_enabled=False)
    assert result["status"] == "inconclusive"
    assert result["pages_added"] == result["pages_removed"] == 1
    assert all(f["change_type"] == "review" for f in result["findings"])
    assert {f["proposed_change_type"] for f in result["findings"]} == {"added", "removed"}


FORM = "INFORME TÉCNICO-MÉDICO PARA LA JUSTIFICACIÓN DE PRESTACIONES ADICIONALES\nCÓDIGO DE VALIDACIÓN QUE AUTORIZÓ PRESTACIÓN: TEST-VALIDACION-2026-001\n"
LABEL = "DIAGNÓSTICO(S) QUE JUSTIFICARON EL CÓDIGO DE VALIDACIÓN: "
CURRENT = "DIGANÓSTICOS ACTUALES QUE JUSTIFICARÁN LA PRESTACIÓN ADICIONAL: K635 POLIPO DEL COLON"

def test_diagnosis_matches_same_field_despite_extraction_order():
    old = FORM + LABEL + 'K635 POLIPO DEL COLON\n' + CURRENT + '\nContenido clínico que permanece'
    new = FORM + 'Contenido clínico que permanece\n' + LABEL + 'K 590 CONSTIPACION\n' + CURRENT
    changes = _line_changes(Page(2, old), Page(29, new))
    assert len(changes) == 1
    finding = changes[0]
    assert finding['change_type'] == 'modified'
    assert finding['category'] == 'Diagnóstico documental'
    assert 'K635' in finding['before'] and 'K 590' in finding['after']
    assert (finding['page_original'], finding['page_modified']) == (2,29)

def test_unique_validation_code_matches_relocated_form():
    a = [Page(2, FORM + LABEL + 'K635 POLIPO DEL COLON'), Page(3, 'Factura mercantil tributaria soporte fiscal proveedor importe total')]
    b = [Page(2, a[1].text), Page(29, FORM + LABEL + 'K590 CONSTIPACION')]
    rows = _align_pages(a,b)
    match = next(row for row in rows if row['page_original']==2)
    assert match['page_modified']==29 and match['relocated']
    assert match['match_basis']=='validation_code_and_form' and not match['review_required']
    assert _document_type(FORM+'Anatomía patológica mencionada en el cuerpo') == 'Informe técnico-médico'

def test_different_validation_codes_do_not_pair_similar_templates():
    rows = _align_pages([Page(1,FORM+LABEL+'K635 POLIPO DEL COLON')], [Page(1,FORM.replace('2026-001','2026-002')+LABEL+'K635 POLIPO DEL COLON')])
    assert all(row['page_original'] is None or row['page_modified'] is None for row in rows)


def test_content_coverage_measures_text_not_findings():
    from app.comparison import Page, content_coverage
    metric = content_coverage([Page(1, 'uno dos tres cuatro')], [Page(1, 'uno dos cinco seis')], [{'page_original':1,'page_modified':1}])
    assert metric['total_units'] == 4
    assert metric['units'] == {'unchanged':2,'added':0,'removed':0,'modified':2,'relocated':0,'review':0}


def test_content_coverage_relocation_and_changes_do_not_overlap():
    from app.comparison import Page, content_coverage
    metric = content_coverage([Page(1, 'uno dos tres cuatro')], [Page(1, 'uno dos cinco seis extra')], [{'page_original':1,'page_modified':1,'relocated':True}])
    assert metric['total_units'] == 5
    assert metric['units']['relocated'] == 2
    assert metric['units']['modified'] == 2
    assert metric['units']['added'] == 1


def test_content_coverage_abstains_for_unreadable_pages():
    from app.comparison import Page, content_coverage
    metric = content_coverage([Page(1, '', readable=False)], [Page(1, 'uno dos tres')], [{'page_original':1,'page_modified':1}])
    assert metric['total_units'] == 0
    assert metric['unmeasured_page_pairs'] == 1


def test_content_coverage_accounts_uncertain_correspondence_and_extraction_order():
    from app.comparison import Page, content_coverage
    pages=[Page(1,'uno dos tres'),Page(2,'cuatro cinco')]
    metric=content_coverage(pages,[Page(1,'tres uno dos'),Page(2,'seis siete')],[{'page_original':1,'page_modified':1},{'page_original':2,'page_modified':2,'review_required':True}])
    assert metric['units']['unchanged'] == 3
    assert metric['units']['review'] == 2
