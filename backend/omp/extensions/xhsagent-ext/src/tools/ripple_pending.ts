/** xhs_ripple_pending — get Ripple decision status and options. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface RipplePendingResponse {
  status: string;
  ripple_prediction: Record<string, unknown>;
  ripple_pmf: Record<string, unknown>;
  ripple_reason: string;
  reselect_count: number;
  max_reselect: number;
  options: string[];
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_ripple_pending",
    label: "XHS Ripple Pending",
    description: "Get Ripple CAS decision status — prediction results and available decision options (accept/reangle/retopic)",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/review/ripple-pending/${params.thread_id}`)) as RipplePendingResponse;

        const prediction = result.ripple_prediction || {};
        const pmf = result.ripple_pmf || {};

        const lines = [
          `Ripple Decision — ${params.thread_id}:`,
          `  Status: ${result.status}`,
          `  Reselect Count: ${result.reselect_count}/${result.max_reselect}`,
          `  Options: ${result.options.join(", ")}`,
        ];

        // Show prediction highlights
        const viralProb = prediction.viral_probability;
        const estReach = prediction.estimated_reach;
        const confidence = prediction.confidence;
        if (viralProb !== undefined) lines.push(`  Viral Probability: ${viralProb}`);
        if (estReach !== undefined) lines.push(`  Estimated Reach: ${estReach}`);
        if (confidence !== undefined) lines.push(`  Confidence: ${confidence}`);

        if (result.ripple_reason) {
          lines.push(`  Reason: ${result.ripple_reason}`);
        }

        // PMF summary
        if (pmf && Object.keys(pmf).length) {
          const score = (pmf as any).pmf_score || (pmf as any).score;
          if (score !== undefined) lines.push(`  PMF Score: ${score}`);
        }

        lines.push("", "Use xhs_ripple_decision to submit your choice.");

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get Ripple status: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
