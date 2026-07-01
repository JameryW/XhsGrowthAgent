/** xhs_evaluation_weights — show the evaluator's current effective grader weights. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface WeightItem {
  weight_key: string;
  value: number;
  is_default: boolean;
}

interface WeightsResponse {
  db_ready: boolean;
  account_id: string | null;
  weights: WeightItem[];
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().optional().describe("按账号隔离权重（可选）"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_evaluation_weights",
    label: "XHS Evaluation Weights",
    description:
      "Show the RQGM evaluator's current effective grader weights (defaults overridden by DB rows). " +
      "Includes dimension weights, pass/reject thresholds, and bias penalty. Use to inspect " +
      "how the evaluator's scoring has been tuned (manually or via auto-evolution).",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const query = params.account_id ? { account_id: params.account_id } : undefined;
        const result = (await get("/evaluation/weights", query)) as WeightsResponse;
        const weights = result.weights || [];
        if (!weights.length) {
          return textResult("无权重数据。", { ...result });
        }
        const lines: string[] = [
          `评估器当前生效权重${result.account_id ? `（account: ${result.account_id}）` : "（全局）"}：`,
        ];
        if (!result.db_ready) lines.push("  ⚠ DB 未就绪，仅显示默认值");
        for (const w of weights) {
          const tag = w.is_default ? " (default)" : " (overridden)";
          lines.push(`  ${w.weight_key}: ${w.value}${tag}`);
        }
        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`获取权重失败: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
