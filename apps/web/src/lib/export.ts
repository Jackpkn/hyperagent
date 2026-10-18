import type { RunResult } from "./protocol";
import { formatCell } from "./format";

function csvEscape(value: string): string {
  return /[",\n\r]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function resultToCsv(result: RunResult): string {
  const header = result.columns.map(csvEscape).join(",");
  const body = result.rows.map((row) =>
    result.columns.map((column) => csvEscape(formatCell(row[column]))).join(","),
  );
  return [header, ...body].join("\r\n");
}

export function resultToMarkdown(result: RunResult): string {
  const parts: string[] = [result.summary.trim()];
  if (result.checklist && result.checklist.length > 0) {
    parts.push(
      "### Checklist\n" +
        result.checklist
          .map((c) => `- [${c.met ? "x" : " "}] ${c.requirement}${c.evidence ? ` — ${c.evidence}` : ""}`)
          .join("\n"),
    );
  }
  if (result.columns.length > 0 && result.rows.length > 0) {
    const escape = (value: string) => value.replace(/\|/g, "\\|").replace(/\n/g, " ");
    const head = `| ${result.columns.map(escape).join(" | ")} |`;
    const rule = `| ${result.columns.map(() => "---").join(" | ")} |`;
    const rows = result.rows.map(
      (row) => `| ${result.columns.map((c) => escape(formatCell(row[c]))).join(" | ")} |`,
    );
    parts.push([head, rule, ...rows].join("\n"));
  }
  if (result.sources.length > 0) {
    parts.push(
      "### Sources\n" + result.sources.map((s) => `- [${s.title || s.url}](${s.url})`).join("\n"),
    );
  }
  if (result.issues.length > 0) {
    parts.push("### Open issues\n" + result.issues.map((issue) => `- ${issue}`).join("\n"));
  }
  if (result.assumptions && result.assumptions.length > 0) {
    parts.push("### Assumptions\n" + result.assumptions.map((a) => `- ${a}`).join("\n"));
  }
  return parts.join("\n\n");
}

export function downloadText(filename: string, content: string, type: string): void {
  const blob = new Blob([content], { type: `${type};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser a tick to start the download before releasing the URL.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
