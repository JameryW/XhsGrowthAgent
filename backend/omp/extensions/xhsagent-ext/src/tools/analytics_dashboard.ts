/** xhs_analytics_dashboard — get analytics dashboard data for an account. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface AnalyticsDashboardResponse {
  report: {
    account_id: string;
    period: string;
    metrics: {
      total_posts: number;
      total_engagement: number;
      avg_engagement_rate: number;
      best_post_title: string;
      trend_topics: string[];
    };
    insights: Array<{ type: string; message: string }>;
    generated_at: string;
  };
  performance: {
    posts: Array<Record<string, unknown>>;
    total: number;
  };
  costs: {
    total_cost_usd: number;
    period_cost_usd: number;
    today_cost_usd: number;
    by_model: Record<string, number>;
  };
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().describe("Account ID to get analytics for"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_analytics_dashboard",
    label: "XHS Analytics Dashboard",
    description: "Get analytics dashboard data for an account (summary, recent posts, top performing content)",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/analytics/dashboard/${params.account_id}`)) as AnalyticsDashboardResponse;

        const lines: string[] = [
          `Analytics Dashboard — ${params.account_id}:`,
        ];

        // Report metrics
        const metrics = result.report?.metrics;
        if (metrics) {
          lines.push(`  Posts: ${metrics.total_posts}, Engagement: ${metrics.total_engagement}, Avg Rate: ${metrics.avg_engagement_rate}%`);
          if (metrics.best_post_title) lines.push(`  Best Post: ${metrics.best_post_title}`);
          if (metrics.trend_topics?.length) lines.push(`  Trend Topics: ${metrics.trend_topics.join(", ")}`);
        }

        // Insights
        const insights = result.report?.insights;
        if (insights?.length) {
          lines.push("", "  Insights:");
          for (const ins of insights) {
            lines.push(`  - ${ins.message}`);
          }
        }

        // Cost summary
        const costs = result.costs;
        if (costs) {
          lines.push("", `  Costs: $${costs.period_cost_usd?.toFixed(2) || "0.00"} this period, $${costs.today_cost_usd?.toFixed(2) || "0.00"} today`);
        }

        // Performance posts count
        const posts = result.performance?.posts;
        if (posts?.length) {
          lines.push(`  Recent Posts: ${posts.length}`);
        }

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get analytics: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
