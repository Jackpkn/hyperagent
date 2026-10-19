"use client";

import { useMemo, useState } from "react";
import { formatCell } from "@/lib/format";
import { ValueEvidence, type EvidenceContext } from "./ValueEvidence";

interface DataTableProps extends EvidenceContext {
  columns: string[];
  rows: Record<string, unknown>[];
  compareRows?: Record<string, unknown>[];
  unverifiedValues?: Set<string>;
}

type SortState = { column: string; direction: "asc" | "desc" } | null;

// Rows that are themselves totals (from a receipt or order summary) must not be summed again.
const SUMMARY_ROW_RE = /^\s*(sub\s*-?\s*total|item\s+total|grand\s+total|total|tax(es)?|vat|gst|shipping|delivery|fees?|discount)\b/i;

// Columns whose values add up to something meaningful. Prices, fares and scores of competing options are left
// out: summing five flights' prices is not a figure anyone asked for.
const QUANTITATIVE_COL_RE =
  /amount|total|subtotal|tax|payout|balance|revenue|margin|qty|quantity|line\s*cost|units/i;

function parseNumericCell(raw: string): { num: number; prefix: string } | null {
  const clean = raw.trim();
  if (!clean) return null;
  const currencyMatch = clean.match(/^([$£€¥₹])\s*(-?\d[\d,]*(?:\.\d+)?)$/);
  if (currencyMatch) {
    const val = Number(currencyMatch[2].replace(/,/g, ""));
    return Number.isFinite(val) ? { num: val, prefix: currencyMatch[1] } : null;
  }
  const numMatch = clean.match(/^(-?\d[\d,]*(?:\.\d+)?)\s*(?:in stock|available|items|points|comments)?$/i);
  if (numMatch) {
    const val = Number(numMatch[1].replace(/,/g, ""));
    return Number.isFinite(val) ? { num: val, prefix: "" } : null;
  }
  return null;
}

function compareValues(a: unknown, b: unknown): number {
  const numA = typeof a === "number" ? a : Number(formatCell(a).replace(/[^0-9.-]/g, ""));
  const numB = typeof b === "number" ? b : Number(formatCell(b).replace(/[^0-9.-]/g, ""));
  const bothNumeric =
    formatCell(a) !== "" &&
    formatCell(b) !== "" &&
    Number.isFinite(numA) &&
    Number.isFinite(numB) &&
    /\d/.test(formatCell(a)) &&
    /\d/.test(formatCell(b));
  if (bothNumeric) return numA - numB;
  return formatCell(a).localeCompare(formatCell(b), undefined, { numeric: true });
}

export function DataTable({
  columns,
  rows,
  compareRows,
  unverifiedValues,
  findings,
  steps,
  captureStepIds,
  selectedStepId,
  onInspectStep,
}: DataTableProps) {
  const [sort, setSort] = useState<SortState>(null);
  const keyColumn = columns[0] ?? "";

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const factor = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => factor * compareValues(a[sort.column], b[sort.column]));
  }, [rows, sort]);

  const compareLookup = useMemo(() => {
    if (!compareRows || compareRows.length === 0) return null;
    const byKey = new Map<string, Record<string, unknown>>();
    if (keyColumn) {
      for (const r of compareRows) {
        const k = formatCell(r[keyColumn]).trim().toLowerCase();
        if (k && !byKey.has(k)) byKey.set(k, r);
      }
    }
    return { byKey, byIndex: compareRows };
  }, [compareRows, keyColumn]);

  // Deterministic numeric column summaries (never relying on LLM arithmetic).
  const columnTotals = useMemo(() => {
    const itemRows = rows.filter((row) => !SUMMARY_ROW_RE.test(formatCell(row[keyColumn])));
    // A table that already carries its own totals needs no second, computed one.
    if (itemRows.length < 2 || itemRows.length < rows.length) return null;
    const map = new Map<string, { sum: number; avg: number; prefix: string; isDecimal: boolean }>();
    for (const col of columns) {
      const parsed: { num: number; prefix: string; raw: string }[] = [];
      for (const row of rows) {
        const raw = formatCell(row[col]);
        const p = parseNumericCell(raw);
        if (p) parsed.push({ ...p, raw });
      }
      if (parsed.length < 2) continue;
      const hasCurrency = parsed.some((p) => p.prefix !== "");
      if (!QUANTITATIVE_COL_RE.test(col)) continue;
      const sum = parsed.reduce((acc, p) => acc + p.num, 0);
      const avg = sum / parsed.length;
      const prefix = parsed.find((p) => p.prefix)?.prefix ?? "";
      const isDecimal = hasCurrency || parsed.some((p) => p.raw.includes("."));
      map.set(col, { sum, avg, prefix, isDecimal });
    }
    return map.size > 0 ? map : null;
  }, [columns, rows, keyColumn]);

  const toggle = (column: string) => {
    setSort((current) => {
      if (!current || current.column !== column) return { column, direction: "asc" };
      if (current.direction === "asc") return { column, direction: "desc" };
      return null;
    });
  };

  return (
    <div className="table-wrap" role="region" aria-label="Extracted data" tabIndex={0}>
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => {
              const active = sort?.column === column;
              return (
                <th
                  key={column}
                  scope="col"
                  aria-sort={
                    active ? (sort.direction === "asc" ? "ascending" : "descending") : "none"
                  }
                >
                  <button type="button" className="sort-button" onClick={() => toggle(column)}>
                    {column}
                    <span aria-hidden="true" className="sort-glyph">
                      {active ? (sort.direction === "asc" ? "↑" : "↓") : "↕"}
                    </span>
                  </button>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, rowIndex) => {
            const keyVal = keyColumn ? formatCell(row[keyColumn]).trim().toLowerCase() : "";
            const prevRow = compareLookup
              ? (keyVal && compareLookup.byKey.get(keyVal)) ?? compareLookup.byIndex[rowIndex]
              : undefined;
            const isNewRow = Boolean(compareLookup && !prevRow);

            return (
              <tr key={rows.indexOf(row)} className={isNewRow ? "is-diff-new-row" : undefined}>
                {columns.map((column, colIdx) => {
                  const currText = formatCell(row[column]);
                  const prevText = prevRow ? formatCell(prevRow[column]) : "";
                  const changed = Boolean(
                    compareLookup && prevRow && column in prevRow && prevText !== currText,
                  );
                  const isSuspect = Boolean(
                    currText && unverifiedValues?.has(currText.trim().toLowerCase()),
                  );
                  return (
                    <td
                      key={column}
                      className={`${changed ? "is-diff-cell " : ""}${isSuspect ? "is-suspect-cell" : ""}`.trim() || undefined}
                    >
                      {colIdx === 0 && isNewRow ? (
                        <span className="diff-badge diff-new">New</span>
                      ) : null}
                      {changed ? (
                        <span className="diff-cell-wrap">
                          <span className="diff-old">{prevText || "–"}</span>
                          <span className="diff-arrow" aria-hidden="true">
                            →
                          </span>
                          <span className="diff-curr">{currText || "–"}</span>
                        </span>
                      ) : (
                        <span>{currText}</span>
                      )}
                      {isSuspect ? (
                        <span
                          className="suspect-inline"
                          title="Value was not found verbatim in observed page text"
                        >
                          ⚠ unverified
                        </span>
                      ) : null}
                      <ValueEvidence row={row} column={column} findings={findings} steps={steps}
                        captureStepIds={captureStepIds} selectedStepId={selectedStepId} onInspectStep={onInspectStep} />
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
        {columnTotals ? (
          <tfoot>
            <tr className="table-reconcile-row" title="Deterministic arithmetic check computed directly by the client">
              {columns.map((column, colIdx) => {
                const stat = columnTotals.get(column);
                if (!stat) {
                  return (
                    <td key={column} className="reconcile-cell">
                      {colIdx === 0 ? <strong className="reconcile-label">Σ Verified Total</strong> : ""}
                    </td>
                  );
                }
                const fmt = (n: number) =>
                  `${stat.prefix}${stat.isDecimal ? n.toFixed(2) : Math.round(n).toLocaleString()}`;
                return (
                  <td key={column} className="reconcile-cell reconcile-stat">
                    <strong>Σ {fmt(stat.sum)}</strong>
                    <span className="reconcile-avg"> · avg {fmt(stat.avg)}</span>
                  </td>
                );
              })}
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
