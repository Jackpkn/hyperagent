import type { Finding } from "./protocol";
import { formatCell } from "./format";

const fieldKey = (key: string) => key.trim().toLowerCase();

/** All nonempty result fields must match by key AND value. A shared price or substring
 * cannot identify a row. Reworded/derived values stay unlinked; ties remain ambiguous.
 */
export function cellFindings(
  row: Record<string, unknown>, column: string, findings: Finding[] = [],
): Finding[] {
  if (!formatCell(row[column]).trim()) return [];
  const entries = Object.entries(row).filter(([, value]) => formatCell(value).trim());
  return findings.filter((finding) => entries.every(([key, value]) => {
    // The source is metadata, not normally a field inside finding.data.
    if (/^source[\s_]*url$/i.test(key.trim())) {
      const source = webUrl(finding.source_url);
      return Boolean(source && webUrl(formatCell(value).trim()) === source);
    }
    const fields = Object.keys(finding.data).filter((candidate) => fieldKey(candidate) === fieldKey(key));
    return fields.length === 1 && formatCell(finding.data[fields[0]]).trim() === formatCell(value).trim();
  }));
}

export function isUnverifiedField(finding: Finding, column: string): boolean {
  return Boolean(finding.unverified?.some((key) => fieldKey(key) === fieldKey(column)));
}

export function webUrl(value: string | undefined): string | null {
  try {
    const url = new URL(value ?? "");
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

export function sameSourcePage(a: string | undefined, b: string | undefined): boolean {
  const first = webUrl(a);
  const second = webUrl(b);
  return Boolean(first && second && first.split("#")[0] === second.split("#")[0]);
}
