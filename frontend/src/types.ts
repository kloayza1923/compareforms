export type Role = 'admin' | 'auditor' | 'supervisor';
export type AuthProvider = 'local' | 'aitrol';
export interface AuthConfig { provider: AuthProvider; password_management: AuthProvider }
export interface User {
  id: string; username: string; role: Role; organization_id: string;
  auth_provider?: AuthProvider; company_id?: string; company_name?: string;
}
export interface Auth { user: User; csrf_token: string }
export interface Company { id: string; name: string }
export type LoginResult = Auth | { requires_company: true; companies: Company[] };
export interface Batch {
  id: string; name: string; period: string; status: string;
  source_mode: 'manual' | 'roboti'; source_system: 'dalia' | 'manual_otro' | 'roboti'; created_at: string | number;
}
export interface Document { id: string; side: 'original' | 'modified'; original_name: string; patient_name: string }
export interface Pair { id: string; patient_name: string; original_id: string; modified_id: string; confirmed: boolean }
export interface Inventory {
  documents: Document[]; pairs: Pair[]; unpaired: Document[];
  rejections: { name: string; reason: string; blocking?: boolean }[]; can_run: boolean;
}
export type ChangeType = 'added' | 'removed' | 'modified' | 'relocated' | 'review';
export interface Finding {
  id: string; change_type: ChangeType; category: string; description: string; before: string; after: string;
  page_original: number | null; page_modified: number | null; confidence: number | null; review_required: boolean;
  source?: 'automatic' | 'manual';
}
export interface Comparison {
  status: string; pages_original: number; pages_modified: number; pages_added: number; pages_removed: number;
  page_counts_reconciled?: boolean;
  pages_relocated: number; findings: Finding[]; page_map: {
    page_original: number | null; page_modified: number | null; status: string; similarity: number; review_required?: boolean;
  }[]; limitations: string[]; engine_version: string;
}
export interface Case {
  id: string; patient_name: string; original_id: string; modified_id: string; status: string; comparison: Comparison | null;
  manual_findings?: Array<Omit<Finding, 'category' | 'confidence' | 'review_required'>>;
  reviews?: Review[];
}
export interface Review { id: string; finding_id: string; decision: 'confirmed' | 'false_positive' | 'needs_review'; comment: string }
export interface Run {
  id: string; batch_id: string; status: string; completed: number; total: number; error: string | null;
  report_available: boolean; cases: Case[]; created_at?: string | number;
}
export interface Capabilities {
  roboti: { enabled: boolean; reason: string };
  ml: { enabled: boolean; architecture: string; unique_pdf_count: number; threshold: number; eligible_for_evaluation: boolean; reason: string };
}
export interface Improvement {
  id: string; run_id: string; case_id: string; finding_id: string; description: string; expected_benefit: string;
  status?: string; created_at?: string | number; source_system?: string;
}
