import type { Case, ChangeType, Finding } from './types';
export const statisticTypes: ChangeType[] = ['added', 'removed', 'modified', 'relocated', 'review'];
export function caseFindings(item: Case): Finding[] {
  return [...(item.comparison?.findings || []), ...(item.manual_findings || []).map(finding => ({ ...finding, category: 'Observación manual', confidence: null, review_required: true }))];
}
export function summarizeCases(cases: Case[]) {
  const counts: Record<ChangeType, number> = { added: 0, removed: 0, modified: 0, relocated: 0, review: 0 };
  let available = 0, affected = 0;
  for (const item of cases) {
    if (!item.comparison) continue;
    available++;
    const findings = caseFindings(item);
    if (findings.length) affected++;
    for (const finding of findings) counts[finding.change_type]++;
  }
  return { counts, total: Object.values(counts).reduce((sum, count) => sum + count, 0), available, affected };
}
export function incidenceCount(item: Case, type: ChangeType | 'all' = 'all') {
  return item.comparison ? caseFindings(item).filter(finding => type === 'all' || finding.change_type === type).length : 0;
}
