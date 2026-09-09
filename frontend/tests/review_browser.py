"""Review UI smoke in standalone and Roboti shells, with synthetic data only."""
import base64, json, sys, threading, tempfile
from pathlib import Path
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from reportlab.pdfgen import canvas
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
from app.evidence import render_evidence
root=Path(__file__).resolve().parents[2]
class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*_):pass
with tempfile.TemporaryDirectory() as directory:
    pdf=Path(directory)/'test.pdf'; c=canvas.Canvas(str(pdf));c.drawString(40,740,'DOCUMENTO SINTETICO DE PRUEBA');c.drawString(40,600,'Importe documental $2,00 $3,3000 $25,30');c.save()
    image=render_evidence(pdf,1,'$2,00 $3,3000 $25,30',ocr_enabled=False)
    pdf_after=Path(directory)/'after.pdf'; c=canvas.Canvas(str(pdf_after));c.drawString(40,740,'DOCUMENTO SINTETICO DE PRUEBA');c.drawString(40,600,'Importe documental $2,00 $3,0000 $25,00');c.save()
    image_after=render_evidence(pdf_after,1,'$2,00 $3,0000 $25,00',ocr_enabled=False)
    finding={'id':'f1','change_type':'modified','category':'Importe documental','description':'Importe modificado','before':'$2,00 $3,3000 $25,30','after':'$2,00 $3,0000 $25,00','page_original':1,'page_modified':1,'confidence':1,'review_required':False}
    other={**finding,'id':'f2','category':'Diagnóstico documental','description':'Diagnóstico modificado','before':'K635 POLIPO DEL COLON','after':'K590 CONSTIPACION','page_original':2,'page_modified':29,'page_relocated':True}
    comparison={'content_coverage':{'method':'aligned-token-coverage-v1','total_units':100,'unmeasured_page_pairs':0,'units':{'unchanged':50,'modified':50,'added':0,'removed':0,'relocated':0,'review':0}},'status':'with_differences','engine_version':'deterministic-a/1.1.0','pages_original':30,'pages_modified':50,'pages_added':0,'pages_removed':0,'pages_relocated':1,'page_map':[],'findings':[finding,other],'limitations':['Limitación de prueba que debe estar cerrada.']}
    run={'id':'r','batch_id':'b','status':'completed','total':1,'completed':1,'report_available':False,'cases':[{'id':'c','patient_name':'PACIENTE DE PRUEBA','original_id':'o','modified_id':'m','status':'completed','comparison':comparison}]}
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        for name,dist,hash_path in [('compareforms',root/'frontend/dist','#/runs/r'),('roboti',root.parent/'roboti/formsgenerator_front/dist','#/compareforms/runs/r')]:
            server=ThreadingHTTPServer(('127.0.0.1',0),partial(Quiet,directory=str(dist)))
            threading.Thread(target=server.serve_forever,daemon=True).start()
            page=browser.new_page(viewport={'width':1600,'height':1050}); errors=[]
            page.on('pageerror',lambda error:errors.append(str(error)))
            def respond(route):
                path=urlsplit(route.request.url).path
                if path.endswith('/evidence'):value=image_after if 'side=modified' in route.request.url else image
                elif path.endswith('/runs/r'):value=run
                elif path.endswith('/auth/config'):value={'provider':'aitrol','password_management':'aitrol'}
                elif path.endswith('/auth/me') or path.endswith('/auth/session'):value={'csrf_token':'test','user':{'id':'u','username':'qa','name':'Usuario de prueba','role':'auditor','email':'qa@example.invalid'}}
                elif path.endswith('/companies'):value=[{'id':'a','name':'Empresa de prueba'}]
                elif path.endswith('/capabilities'):value={'roboti':{'enabled':False}}
                elif path.endswith('/insurances'):value=[]
                else:errors.append('Unexpected API '+path);value={}
                route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
            page.route('**/api/**',respond)
            page.goto(f'http://127.0.0.1:{server.server_port}/{hash_path}')
            expect(page.get_by_role('heading',name='Observaciones documentales')).to_be_visible()
            summary=page.get_by_role('region',name='Resumen estadístico de la revisión')
            expect(summary).to_be_visible()
            expect(summary.get_by_role('img')).to_have_attribute('aria-label','Texto comparado: 50% con cambios o por revisar; 50% sin cambios')
            summary.get_by_role('button',name='Modificado 50% 2 incidencias').click()
            expect(page.get_by_label('Filtrar por tipo de cambio')).to_have_value('modified')
            summary.get_by_role('button',name='Ver todas las incidencias').click()
            out=root.parent/'roboti/output/evidence-qa';out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/(name+'-statistics.png')))
            expect(page.get_by_text('Limitación de prueba que debe estar cerrada.')).not_to_be_visible()
            expect(page.get_by_role('button',name='Añadir observación')).to_have_count(0)
            page.get_by_label('Pág. desde').fill('29');page.get_by_label('Pág. hasta').fill('29')
            expect(page.get_by_text('Importe modificado',exact=True)).to_be_visible()
            page.get_by_role('button',name='Buscar',exact=True).click()
            expect(page.get_by_text('Importe modificado',exact=True)).to_have_count(0)
            expect(page.get_by_text('Diagnóstico modificado',exact=True)).to_be_visible()
            page.get_by_label('Pág. desde').fill('');page.get_by_label('Pág. hasta').fill('')
            page.get_by_role('button',name='Buscar',exact=True).click()
            page.get_by_role('button',name='Ver evidencia',exact=True).first.click()
            dialog=page.get_by_role('dialog',name='Evidencia de la observación')
            expect(dialog).to_be_visible();expect(dialog.get_by_role('img')).to_have_count(2)
            page.wait_for_function("() => [...document.querySelectorAll('dialog img')].every(i => i.complete)") if name=='compareforms' else None
            out=root.parent/'roboti/output/evidence-qa';out.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(out/(name+'-review.png')))
            page.keyboard.press('Escape');expect(dialog).to_have_count(0)
            page.set_viewport_size({'width':390,'height':844})
            page.get_by_role('button',name='Ver evidencia',exact=True).first.click()
            expect(page.get_by_role('dialog')).to_be_visible()
            page.get_by_role('button',name='Cerrar evidencia').click()
            assert not errors,errors
            page.close();server.shutdown();print(name+': filters, modal, highlights, Escape and mobile passed')
        browser.close()
