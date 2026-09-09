import type { Case, ChangeType, Finding } from './types';
export const statisticTypes: ChangeType[] = ['added', 'removed', 'modified', 'relocated', 'review'];
export function caseFindings(item: Case): Finding[] {
  return [...(item.comparison?.findings || []), ...(item.manual_findings || []).map(finding => ({ ...finding, category: 'Observación manual', confidence: null, review_required: true }))];
}
export function summarizeCases(cases: Case[]) {
  const counts: Record<ChangeType, number> = { added: 0, removed: 0, modified: 0, relocated: 0, review: 0 };
  let available = 0, affected = 0, measured = 0, unmeasuredPages = 0, graphicFindings = 0;
  const units = { unchanged: 0, added: 0, removed: 0, modified: 0, relocated: 0, review: 0 };
  for (const item of cases) {
    if (!item.comparison) continue;
    available++;
    const metric = item.comparison.content_coverage;
    if (metric?.method === 'aligned-token-coverage-v1') {
      measured++; unmeasuredPages += metric.unmeasured_page_pairs; graphicFindings += metric.graphic_findings || 0;
      for (const type of [...statisticTypes, 'unchanged'] as const) units[type] += metric.units[type];
    }
    const findings = caseFindings(item);
    if (findings.length) affected++;
    for (const finding of findings) counts[finding.change_type]++;
  }
  return { counts, total: Object.values(counts).reduce((sum, count) => sum + count, 0), available, affected, measured, units, unmeasuredPages, graphicFindings };
}
export function incidenceCount(item: Case, type: ChangeType | 'all' = 'all') {
  return item.comparison ? caseFindings(item).filter(finding => type === 'all' || finding.change_type === type).length : 0;
}

// Largest remainder at 0.1 percentage point: displayed slices sum to exactly 100%.
export function coveragePercentages(units: Record<ChangeType | 'unchanged', number>) {
  const keys = [...statisticTypes, 'unchanged'] as const;
  const total = keys.reduce((sum, key) => sum + units[key], 0);
  const values = keys.map(key => total ? units[key] * 1000 / total : 0);
  const tenths = values.map(Math.floor);
  const remaining = total ? 1000 - tenths.reduce((sum, value) => sum + value, 0) : 0;
  [...keys.keys()].sort((a,b) => (values[b] - tenths[b]) - (values[a] - tenths[a])).slice(0, remaining).forEach(index => tenths[index]++);
  return Object.fromEntries(keys.map((key, index) => [key, tenths[index] / 10])) as Record<ChangeType | 'unchanged', number>;
}
