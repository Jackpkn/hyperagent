"use client";

import { useMemo, useState } from "react";
import { formatCell } from "@/lib/format";

interface DataTableProps {
  columns: string[];
  rows: Record<string, unknown>[];
  compareRows?: Record<string, unknown>[];
  unverifiedValues?: Set<string>;
}

type SortState = { column: string; direction: "asc" | "desc" } | null;

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

export function DataTable({ columns, rows, compareRows, unverifiedValues }: DataTableProps) {
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
              <tr key={rowIndex} className={isNewRow ? "is-diff-new-row" : undefined}>
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
                        currText
                      )}
                      {isSuspect ? (
                        <span
                          className="suspect-inline"
                          title="Value was not found verbatim in observed page text"
                        >
                          ⚠ unverified
                        </span>
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
