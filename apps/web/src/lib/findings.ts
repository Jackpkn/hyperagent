import type { Finding } from "./protocol";
import { formatCell } from "./format";

/** The saved finding (with a step snapshot) that best matches a result row, for click-to-verify receipts. */
export function matchRowToFinding(
  row: Record<string, unknown>,
  findings: Finding[] | undefined,
): Finding | undefined {
  if (!findings || findings.length === 0) return undefined;
  const rowStrings = Object.values(row)
    .map((v) => formatCell(v).trim().toLowerCase())
    .filter((s) => s.length >= 3);
  if (rowStrings.length === 0) return undefined;
  let best: Finding | undefined;
  let bestScore = 0;
  for (const f of findings) {
    if (!f.step_id) continue;
    const fVals = Object.values(f.data).map((v) => formatCell(v).trim().toLowerCase());
    const score = rowStrings.filter((rv) =>
      fVals.some((fv) => fv && (fv === rv || fv.includes(rv) || rv.includes(fv))),
    ).length;
    if (score > bestScore) {
      bestScore = score;
      best = f;
    }
  }
  return best;
}
