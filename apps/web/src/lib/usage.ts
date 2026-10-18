import type { Usage } from "./protocol";

/** Each input is the latest cumulative snapshot for one distinct task. */
export function sumUsage(items: readonly (Usage | null | undefined)[]): Usage {
  return items.reduce<Usage>((total, usage) => ({
    llm_calls: total.llm_calls + (usage?.llm_calls ?? 0),
    input_tokens: total.input_tokens + (usage?.input_tokens ?? 0),
    output_tokens: total.output_tokens + (usage?.output_tokens ?? 0),
    cost_usd: total.cost_usd + (usage?.cost_usd ?? 0),
    elapsed_s: total.elapsed_s + (usage?.elapsed_s ?? 0),
  }), { llm_calls: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0, elapsed_s: 0 });
}

export function totalTokens(usage: Usage | null): number {
  return (usage?.input_tokens ?? 0) + (usage?.output_tokens ?? 0);
}
