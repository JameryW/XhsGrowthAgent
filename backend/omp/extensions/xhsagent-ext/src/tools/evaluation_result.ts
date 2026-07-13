/** xhs_evaluation_result — get the RQGM agent-as-a-judge quality evaluation for a thread. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface DimensionScore {
  dimension: string;
  score: number;
  /** bias_check 维度专属：偏倚严重度（0-100，越高越糟），旧样本可能缺省 */
  bias_severity?: number;
  rationale: string;
  issues: string[];
  is_blocking: boolean;
}

interface EvaluationResult {
  overall_score: number;
  dimensions: DimensionScore[];
  decision: string;
  revision_hints: string[];
  bias_warning: string;
  summary: string;
}

interface EvaluationResultResponse {
  thread_id: string;
  has_evaluation: boolean;
  evaluation_result: EvaluationResult;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_evaluation_result",
    label: "XHS Evaluation Result",
    description:
      "Get the creation-quality evaluation (RQGM agent-as-a-judge panel) for a workflow. Returns 10-dimension scores (copywriting/visual/compliance/reach/audience/ai_taste/image_quality/commercial_tone/altruism/bias_check), overall score, decision (approved/needs_revision/rejected), and revision hints.",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(
          `/evaluation/result/${params.thread_id}`,
        )) as EvaluationResultResponse;

        if (!result.has_evaluation) {
          return textResult(
            `No evaluation result yet for ${params.thread_id}. Run xhs_evaluation_run to evaluate, or the workflow will evaluate automatically before publish.`,
            { thread_id: params.thread_id, has_evaluation: false },
          );
        }

        const ev = result.evaluation_result;
        const lines: string[] = [
          `Creation Quality Evaluation — ${params.thread_id}:`,
          `  Overall: ${ev.overall_score ?? "N/A"}  Decision: ${ev.decision}`,
        ];
        if (ev.summary) lines.push(`  Summary: ${ev.summary}`);
        if (ev.bias_warning) lines.push(`  ⚠ Bias: ${ev.bias_warning}`);
        for (const d of ev.dimensions || []) {
          const block = d.is_blocking ? " [BLOCKING]" : "";
          lines.push(`  - ${d.dimension}: ${d.score}${block} — ${d.rationale}`);
          for (const issue of d.issues || []) lines.push(`      • ${issue}`);
        }
        if (ev.revision_hints && ev.revision_hints.length) {
          lines.push("  Revision hints:");
          for (const h of ev.revision_hints) lines.push(`    - ${h}`);
        }

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get evaluation: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
