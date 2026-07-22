/** xhs_analytics_report — get growth report for an account. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { formatAnalyticsRate } from "../analytics_format.js";
import { textResult } from "../types.js";

interface MetricsData {
  total_posts: number;
  total_engagement: number;
  avg_engagement_rate: number;
  best_post_title: string;
  trend_topics: string[];
}

interface InsightEntry {
  type: string;
  message: string;
}

interface ReportResponse {
  account_id: string;
  period: string;
  metrics: MetricsData;
  insights: InsightEntry[];
  generated_at: string;
  engagement_rate_unit?: "fraction" | "percent" | string;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().describe("Account ID"),
    period: pi.zod.string().default("weekly").describe("Time period: daily, weekly, monthly"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_analytics_report",
    label: "XHS Analytics Report",
    description: "Get growth report for an account — metrics, insights, and trend topics",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/analytics/report/${params.account_id}`, {
          period: params.period,
        })) as ReportResponse;

        const m = result.metrics || {};
        const lines = [
          `Growth Report — ${params.account_id} (${params.period}):`,
          `  Posts: ${m.total_posts || 0}`,
          `  Total Engagement: ${m.total_engagement || 0}`,
          `  Avg Engagement Rate: ${formatAnalyticsRate(m.avg_engagement_rate, result.engagement_rate_unit)}`,
        ];

        if (m.best_post_title) {
          lines.push(`  Best Post: ${m.best_post_title}`);
        }
        if (m.trend_topics?.length) {
          lines.push(`  Trend Topics: ${m.trend_topics.join(", ")}`);
        }

        if (result.insights?.length) {
          lines.push("", "  Insights:");
          for (const ins of result.insights) {
            lines.push(`  - ${ins.message}`);
          }
        }

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get report: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
