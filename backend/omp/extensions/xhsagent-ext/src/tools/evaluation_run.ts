/** xhs_evaluation_run — manually trigger RQGM agent-as-a-judge evaluation on a thread's current content. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

interface EvaluationResult {
  overall_score: number;
  decision: string;
  bias_warning: string;
  summary: string;
  dimensions: { dimension: string; score: number; is_blocking: boolean }[];
  revision_hints: string[];
}

interface RunEvaluationResponse {
  thread_id: string;
  status: string;
  evaluation_result: EvaluationResult;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_evaluation_run",
    label: "XHS Evaluation Run",
    description:
      "Manually evaluate the current copy/visual content of a workflow using the RQGM agent-as-a-judge panel (10 dimensions including AI taste, image quality, commercial tone, altruism, and adversarial bias check). Does NOT advance the workflow. Use xhs_evaluation_result to read a prior evaluation.",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await post(
          `/evaluation/run/${params.thread_id}`,
        )) as RunEvaluationResponse;

        const ev = result.evaluation_result;
        const lines: string[] = [
          `Evaluation complete — ${params.thread_id}:`,
          `  Overall: ${ev.overall_score ?? "N/A"}  Decision: ${ev.decision}`,
        ];
        if (ev.summary) lines.push(`  Summary: ${ev.summary}`);
        if (ev.bias_warning) lines.push(`  ⚠ Bias: ${ev.bias_warning}`);
        for (const d of ev.dimensions || []) {
          const block = d.is_blocking ? " [BLOCKING]" : "";
          lines.push(`  - ${d.dimension}: ${d.score}${block}`);
        }
        if (ev.revision_hints && ev.revision_hints.length) {
          lines.push("  Revision hints:");
          for (const h of ev.revision_hints) lines.push(`    - ${h}`);
        }

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to run evaluation: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
