import type { ReactNode } from 'react';
import { changeLabels, stateLabel } from './presentation';
import type { ChangeType } from './types';

export function Icon({ name = 'document', size = 20 }: { name?: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    document: <><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M8 13h8M8 17h5" /></>,
    plus: <path d="M12 5v14M5 12h14" />,
    history: <><path d="M3 11a9 9 0 1 1 2.8 7M3 4v7h7" /><path d="M12 7v5l3 2" /></>,
    shield: <><path d="M12 3 3 7v5c0 5 9 9 9 9s9-4 9-9V7z" /><path d="m8 12 3 3 5-6" /></>,
    users: <><circle cx="9" cy="8" r="3" /><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M21 21v-3a6 6 0 0 0-4-5" /></>,
    model: <><circle cx="12" cy="12" r="4" /><path d="M12 2v6M12 16v6M2 12h6M16 12h6M5 5l4 4M15 15l4 4M19 5l-4 4M9 15l-4 4" /></>,
    upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 16v5h16v-5" /></>,
    download: <><path d="M12 3v13m-5-5 5 5 5-5M4 16v5h16v-5" /></>,
    arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
    check: <path d="m5 12 4 4L19 6" />,
  };
  return <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{paths[name] || paths.document}</svg>;
}
export function Notice({ children, tone = 'info' }: { children: ReactNode; tone?: 'info' | 'warning' | 'danger' | 'success' }) {
  return <div className={`alert alert-${tone}`} role={tone === 'danger' ? 'alert' : 'status'}>{children}</div>;
}
export function Busy({ text = 'Cargando información…' }: { text?: string }) {
  return <div className="busy-state" role="status"><span className="spinner-border spinner-border-sm" /> {text}</div>;
}
export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon size={28} /></span><h3>{title}</h3><p>{children}</p></div>;
}
export function StateBadge({ status }: { status: string }) {
  const tone = ['failed', 'error'].includes(status) ? 'danger' : ['partial', 'inconclusive', 'with_differences', 'needs_pairing', 'manual_observations'].includes(status) ? 'warning' : ['no_differences_detected', 'completed', 'ready'].includes(status) ? 'success' : 'neutral';
  return <span className={`state-badge badge-${tone}`}>{stateLabel(status)}</span>;
}
export function ChangeBadge({ type }: { type: ChangeType }) { return <span className={`change-badge change-${type}`}>{changeLabels[type] || type}</span>; }
export function PageHeading({ eyebrow = 'AUDITORÍA DOCUMENTAL', title, children, action }: { eyebrow?: string; title: string; children?: ReactNode; action?: ReactNode }) {
  return <header className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children && <p className="page-description">{children}</p>}</div>{action && <div className="heading-action">{action}</div>}</header>;
}
export function StepTitle({ number, title, children }: { number: number; title: string; children?: ReactNode }) {
  return <div className="step-heading"><span className="step-number">{number}</span><div><h2>{title}</h2>{children && <p>{children}</p>}</div></div>;
}
