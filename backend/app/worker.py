"""Durable PostgreSQL worker. Run separately: python -m app.worker."""
import argparse
import hashlib
from threading import Event, Thread
import time
from sqlalchemy import select, or_, and_, update, text
from .config import Settings
from . import db as m
from .storage import private_path

def claim(factory, cfg):
    with factory.begin() as db:
        expired = and_(m.Run.status == "running", m.Run.lease_until < m.now())
        exhausted = db.scalars(select(m.Run).where(expired, m.Run.attempts >= cfg.max_attempts).with_for_update(skip_locked=True)).all()
        for r in exhausted:
            r.status = "failed"; r.error = "Se agotaron los reintentos del trabajador. Los resultados parciales se conservan."; r.lease_owner = None
        r = db.scalar(select(m.Run).where(or_(m.Run.status == "queued", expired), m.Run.attempts < cfg.max_attempts).order_by(m.Run.created_at).with_for_update(skip_locked=True).limit(1))
        if not r: return None
        r.status = "running"; r.lease_owner = m.uid(); r.lease_until = m.now() + cfg.lease_seconds; r.attempts += 1
        return r.id, r.lease_owner

def heartbeat(factory, cfg, run_id, token, stop):
    while not stop.wait(max(1, cfg.lease_seconds//3)):
        try:
            with factory.begin() as db:
                changed = db.execute(update(m.Run).where(m.Run.id == run_id, m.Run.lease_owner == token, m.Run.status == "running").values(lease_until=m.now()+cfg.lease_seconds)).rowcount
                if not changed: return
        except Exception: return  # Publishing still checks a live lease.

def owns(r, token): return r and r.status == "running" and r.lease_owner == token and (r.lease_until or 0) > m.now()
def serialize(c): return {k: getattr(c, k) for k in ("id", "patient_name", "original_id", "modified_id", "status", "comparison")}

def process(factory, cfg, run_id, token):
    from .strategies import MinimumErrorStrategy
    from .reporting import write_report
    with factory() as db:
        r = db.get(m.Run, run_id); batch = db.get(m.Batch, r.batch_id)
        ids = list(db.scalars(select(m.RunCase.id).where(m.RunCase.run_id == run_id)))
        period, batch_id = batch.period, batch.id
    for case_id in ids:
        with factory() as db:
            if not owns(db.get(m.Run, run_id), token): return
            case = db.get(m.RunCase, case_id)
            if case.status != "pending": continue
            original, modified = db.get(m.Document, case.original_id), db.get(m.Document, case.modified_id)
            docs = [(private_path(cfg.documents_root, d.storage_key), d.sha256) for d in (original, modified)]
        try:
            for path, expected in docs:
                with path.open("rb") as source: actual = hashlib.file_digest(source, "sha256").hexdigest()
                if actual != expected: raise ValueError("La integridad del PDF cambió respecto al snapshot.")
            result = MinimumErrorStrategy().compare(docs[0][0], docs[1][0], ocr_enabled=cfg.ocr_enabled)
            status = result["status"]
        except Exception as exc:
            status = "error"
            result = {"status": "inconclusive", "pages_original": 0, "pages_modified": 0, "findings": [], "page_map": [], "limitations": [f"No se completó el análisis: {type(exc).__name__}. Revise integridad y límites del documento."], "engine_version": "A-v1"}
        with factory.begin() as db:
            r = db.scalar(select(m.Run).where(m.Run.id == run_id).with_for_update())
            if not owns(r, token): return
            c = db.get(m.RunCase, case_id); c.status, c.comparison = status, result
            r.completed += 1
    with factory() as db:
        r = db.get(m.Run, run_id)
        if not owns(r, token): return
        cases = [serialize(c) for c in db.scalars(select(m.RunCase).where(m.RunCase.run_id == run_id))]
        partial = r.partial_scope or any(c["status"] in ("error", "inconclusive", "pending") for c in cases)
        status = "partial" if partial else "completed"
    key = f"{period}/batches/{batch_id}/runs/{run_id}/{token}/comparativo.xlsx"
    target = private_path(cfg.documents_root, key)
    target.parent.mkdir(parents=True, exist_ok=True)
    write_report(target, period=period, run_id=run_id, cases=cases, status=status)
    with factory.begin() as db:
        r = db.scalar(select(m.Run).where(m.Run.id == run_id).with_for_update())
        if not owns(r, token): return
        r.report_key, r.status = key, status
        r.lease_owner = None

def run_once(cfg, factory=None):
    if factory is None: _, factory = m.connect(cfg)
    engine = factory.kw["bind"]
    if engine.dialect.name == "postgresql":
        # One expensive worker at a time across processes, not merely Python threads.
        with engine.connect() as guard:
            if not guard.scalar(text("SELECT pg_try_advisory_lock(1870025201)")): return False
            try: return _run_once(cfg, factory)
            finally: guard.execute(text("SELECT pg_advisory_unlock(1870025201)"))
    return _run_once(cfg, factory)

def _run_once(cfg, factory):
    job = claim(factory, cfg)
    if not job: return False
    run_id, token = job
    stop = Event(); thread = Thread(target=heartbeat, args=(factory, cfg, run_id, token, stop), daemon=True); thread.start()
    try: process(factory, cfg, run_id, token)
    except Exception as exc:
        with factory.begin() as db:
            r = db.get(m.Run, run_id)
            if owns(r, token):
                r.status = "failed"; r.error = f"No se pudo finalizar el reporte ({type(exc).__name__})."; r.lease_owner = None
    finally: stop.set(); thread.join(timeout=2)
    return True

def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--once", action="store_true"); args = parser.parse_args()
    cfg = Settings(); _, factory = m.connect(cfg)
    while True:
        did_work = run_once(cfg, factory)
        if args.once: return
        if not did_work: time.sleep(2)

if __name__ == "__main__": main()
