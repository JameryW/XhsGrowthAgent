/** xhs_analytics_performance — get recent post performance data. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { formatAnalyticsRate } from "../analytics_format.js";
import { textResult } from "../types.js";

interface PostData {
  title: string;
  likes: number;
  comments: number;
  collects: number;
  engagement_rate: number;
  published_at: string;
}

interface PerformanceResponse {
  account_id: string;
  period: string;
  posts: PostData[];
  total: number;
  fetched_at: string;
  engagement_rate_unit?: "fraction" | "percent" | string;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().describe("Account ID"),
    period: pi.zod.string().default("weekly").describe("Time period: daily, weekly, monthly"),
    limit: pi.zod.number().default(10).describe("Max posts to return (1-100)"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_analytics_performance",
    label: "XHS Analytics Performance",
    description: "Get recent post performance data for an account — likes, comments, engagement rate",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/analytics/performance/${params.account_id}`, {
          period: params.period,
          limit: params.limit,
        })) as PerformanceResponse;

        if (!result.posts?.length) {
          return textResult("No post performance data available yet.", { ...result });
        }

        const lines = [
          `Post Performance — ${params.account_id} (${params.period}, ${result.total} posts):`,
          "",
          ...result.posts.map((p, i) =>
            `  ${i + 1}. ${p.title || "(untitled)"} — ❤️${p.likes} 💬${p.comments} ⭐${p.collects} (${formatAnalyticsRate(p.engagement_rate, result.engagement_rate_unit)} engagement)`
          ),
        ];

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get performance: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
