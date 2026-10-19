import type { RunAccounting, Usage } from "./protocol";

/** Legacy totals remain readable; missing provider cost must never look like a full total. */
export function usageCost(usage?: Usage | null, accounting = usage?.accounting) {
  if (!accounting) {
    return {
      amount: usage?.cost_usd,
      label: "Legacy subtotal",
      description: "Legacy subtotal: planner and extraction only; excludes Jev, text helper and some failed attempts.",
    };
  }
  const summary = accounting.summary;
  if (summary.total_cost_usd === null) {
    return {
      amount: summary.known_cost_usd,
      label: "Known cost",
      description: `Known cost (includes available estimates): ${summary.unknown_cost_count} model attempts have unknown cost; this is not the full total.`,
    };
  }
  const estimated = summary.cost_basis === "estimate";
  return {
    amount: summary.total_cost_usd,
    label: estimated ? "Estimated total" : "Reported total",
    description: estimated
      ? "Estimated total using configured model rates and available provider-reported costs."
      : "Total cost reported by model providers.",
  };
}

export function fastUsage(usage?: Usage | null, accounting?: RunAccounting) {
  const measured = accounting ?? usage?.accounting;
  const calls = measured?.by_purpose.jev.attempts ?? usage?.fast_calls ?? 0;
  const duration = measured?.by_purpose.jev.duration_ms ?? usage?.fast_ms_total ?? 0;
  return { calls, avgMs: calls ? Math.round(duration / calls) : 0, actions: measured?.executed_fast_actions };
}
