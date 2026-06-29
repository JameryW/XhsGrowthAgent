/** xhs_analytics_costs — get LLM cost tracking data. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface AnalyticsCostsResponse {
  total_cost_usd: number;
  period_cost_usd: number;
  today_cost_usd: number;
  period: string;
  by_model: Record<string, number>;
  circuit_open: boolean;
  budget_remaining_usd: number;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    period: pi.zod.string().default("weekly").describe("Time period: daily, weekly, monthly"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_analytics_costs",
    label: "XHS Analytics Costs",
    description: "Get LLM cost tracking data across all workflows",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/analytics/costs`, { period: params.period })) as AnalyticsCostsResponse;

        const lines = [
          `LLM Cost Report (period: ${params.period}):`,
          `  Total: $${result.total_cost_usd?.toFixed(4) || "0.0000"}`,
          `  This Period: $${result.period_cost_usd?.toFixed(4) || "0.0000"}`,
          `  Today: $${result.today_cost_usd?.toFixed(4) || "0.0000"}`,
        ];

        const byModel = result.by_model;
        if (byModel && Object.keys(byModel).length) {
          lines.push("  By Model:");
          for (const [model, cost] of Object.entries(byModel)) {
            lines.push(`    ${model}: $${cost.toFixed(4)}`);
          }
        }

        if (result.budget_remaining_usd !== undefined) {
          lines.push(`  Budget Remaining: $${result.budget_remaining_usd.toFixed(2)}`);
        }

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get cost data: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
