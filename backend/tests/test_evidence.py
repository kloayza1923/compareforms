import base64
from io import BytesIO
import pytest
from PIL import Image
from reportlab.pdfgen import canvas
from pypdf import PdfWriter
from app.evidence import render_evidence
from test_portal_v1 import portal, client, login, completed_fixture

def test_yellow_region_is_located_on_pdf_and_file_is_unchanged(tmp_path):
    path=tmp_path/'fixture.pdf'; c=canvas.Canvas(str(path)); c.drawString(50,700,'Importe documental $2,00 $3,3000 $25,30');c.save()
    before=path.read_bytes()
    result=render_evidence(path,1,'$2,00 $3,3000 $25,30',ocr_enabled=False)
    assert result['highlighted'] and result['regions']
    im=Image.open(BytesIO(base64.b64decode(result['image'].split(',')[1])))
    assert any(r>220 and g>180 and b<100 for r,g,b in im.getdata())
    assert path.read_bytes()==before
    absent=render_evidence(path,1,'Contenido que no existe',ocr_enabled=False)
    assert not absent['highlighted']

def test_oversized_pdf_is_rejected_before_render(tmp_path):
    path=tmp_path/'oversized.pdf'; w=PdfWriter();w.add_blank_page(width=100000,height=100000);w.write(path)
    with pytest.raises(ValueError):render_evidence(path,1,'texto',ocr_enabled=False)

def test_evidence_requires_own_case_and_existing_finding(portal,client,monkeypatch):
    headers=login(client)
    run_id,case_id,finding=completed_fixture(portal,client,headers)
    import app.evidence as module
    calls=[]
    def render(path,page,content,**kwargs):
        calls.append((page,content));return {'image':'data:image/png;base64,aQ==','highlighted':True,'page':page}
    monkeypatch.setattr(module,'render_evidence',render)
    url=f'/api/v1/runs/{run_id}/cases/{case_id}/findings/{finding["id"]}/evidence?side=original'
    response=client.get(url)
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='no-store'
    assert len(calls)==1
    assert client.get(url.replace(finding['id'],'missing')).status_code==404
    login(client,'other_test')
    assert client.get(url).status_code==404
    assert len(calls)==1
