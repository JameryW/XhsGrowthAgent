/** xhs_evaluation_epochs — list RQGM prompt epoch evolution history. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface PromptEpoch {
  epoch_id: number;
  bias_severity: string;
  note: string;
  active: boolean;
  created_at: string;
}

interface EpochsResponse {
  db_ready: boolean;
  epochs: PromptEpoch[];
}

export default function register(pi: ExtensionAPI) {
  const tool: ToolDefinition = {
    name: "xhs_evaluation_epochs",
    label: "XHS Evaluation Epochs",
    description:
      "List the RQGM evaluator's prompt-epoch evolution history (newest first), " +
      "including the currently active epoch and its bias_severity level. " +
      "Use to see how the evaluator has self-tuned its judging strictness over time.",
    parameters: pi.zod.object({}),
    async execute(_id, _params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get("/evaluation/epochs")) as EpochsResponse;
        if (!result.db_ready) {
          return textResult("评估器 epoch 数据库未就绪，暂无 epoch 历史。", { db_ready: false });
        }
        const epochs = result.epochs || [];
        if (!epochs.length) {
          return textResult("尚无 epoch 记录（评估器未演化过）。", { db_ready: true, epochs: [] });
        }
        const active = epochs.find((e) => e.active);
        const lines: string[] = ["评估器 Prompt Epoch 演化历史（newest first）："];
        if (active) {
          lines.push(`▶ 当前 active: #${active.epoch_id} (${active.bias_severity})`);
        }
        for (const e of epochs) {
          const mark = e.active ? " *" : "";
          lines.push(`  #${e.epoch_id} ${e.bias_severity}${mark} — ${e.created_at}`);
          if (e.note) lines.push(`      ${e.note}`);
        }
        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`获取 epoch 历史失败: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
