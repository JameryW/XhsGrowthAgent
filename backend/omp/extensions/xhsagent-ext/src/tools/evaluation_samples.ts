/** xhs_evaluation_samples — export recent evaluator training samples. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface SamplesResponse {
  db_ready: boolean;
  samples: Record<string, unknown>[];
  count?: number;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    account_id: pi.zod.string().optional().describe("按账号过滤（可选）"),
    limit: pi.zod.number().optional().describe("最多返回条数（默认 100）"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_evaluation_samples",
    label: "XHS Evaluation Samples",
    description:
      "Export recent evaluator training samples (each = one judgment + optional engagement weak label). " +
      "Use to inspect what data the evaluator has accumulated for weight training / finetuning.",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const query: Record<string, unknown> = {};
        if (params.account_id) query.account_id = params.account_id;
        if (params.limit) query.limit = params.limit;
        const result = (await get("/evaluation/samples", query)) as SamplesResponse;
        if (!result.db_ready) {
          return textResult("评估器样本数据库未就绪。", { db_ready: false });
        }
        const samples = result.samples || [];
        if (!samples.length) {
          return textResult("尚无训练样本。", { db_ready: true, count: 0 });
        }
        const lines: string[] = [`训练样本（共 ${result.count ?? samples.length} 条）：`];
        for (const s of samples.slice(0, 20)) {
          const tid = s.thread_id ?? "?";
          const score = s.overall_score ?? "?";
          const dec = s.decision ?? "?";
          const labeled = s.engagement ? " [labeled]" : "";
          lines.push(`  thread=${tid} score=${score} decision=${dec}${labeled}`);
        }
        if (samples.length > 20) lines.push(`  ...（仅显示前 20 条，共 ${result.count ?? samples.length}）`);
        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`获取样本失败: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
