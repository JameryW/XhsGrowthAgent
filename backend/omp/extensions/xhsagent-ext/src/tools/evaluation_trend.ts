/** xhs_evaluation_trend — show evaluator score timeline + per-dimension averages. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface TrendPoint {
  created_at: string;
  overall_score: number;
  decision: string;
  dim_scores: Record<string, number>;
}

interface TrendResponse {
  db_ready: boolean;
  points: TrendPoint[];
  dim_averages: Record<string, number>;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().optional().describe("按账号过滤（可选）"),
    limit: pi.zod.number().optional().describe("最多返回点数（默认 100）"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_evaluation_trend",
    label: "XHS Evaluation Trend",
    description:
      "Show the evaluator's historical trend: overall_score timeline + per-dimension averages. " +
      "Use to see whether content quality (as judged) is improving or drifting over time.",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const query: Record<string, unknown> = {};
        if (params.account_id) query.account_id = params.account_id;
        if (params.limit) query.limit = params.limit;
        const result = (await get("/evaluation/trend", query)) as TrendResponse;
        if (!result.db_ready) {
          return textResult("评估器趋势数据库未就绪。", { db_ready: false });
        }
        const points = result.points || [];
        if (!points.length) {
          return textResult("尚无评估历史趋势数据。", { db_ready: true, points: [] });
        }
        const lines: string[] = [`评估历史趋势（${points.length} 个样本）：`];
        const dimAvg = result.dim_averages || {};
        if (Object.keys(dimAvg).length) {
          lines.push("维度均值：");
          for (const [dim, avg] of Object.entries(dimAvg)) {
            lines.push(`  ${dim}: ${avg}`);
          }
        }
        lines.push("overall_score 时序（最近 → 最早）：");
        for (const p of points.slice(0, 20)) {
          lines.push(`  ${p.created_at} — ${p.overall_score} (${p.decision})`);
        }
        if (points.length > 20) lines.push(`  ...（仅显示前 20 个，共 ${points.length}）`);
        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`获取趋势失败: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
