/** xhs_ripple_decision — submit Ripple CAS decision (accept/reangle/retopic). */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

interface RippleDecisionResponse {
  thread_id: string;
  status: string;
  action: string;
  next_phase: string;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
    action: pi.zod.enum(["accept", "reangle", "retopic"]).describe("Decision: accept the prediction, reangle (change angle), or retopic (change topic entirely)"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_ripple_decision",
    label: "XHS Ripple Decision",
    description: "Submit Ripple CAS decision — accept the prediction, change angle, or change topic entirely",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await post(`/review/ripple-decision/${params.thread_id}`, {
          action: params.action,
        })) as RippleDecisionResponse;

        const actionLabel: Record<string, string> = {
          accept: "Accepted Ripple prediction",
          reangle: "Requested angle change",
          retopic: "Requested topic change",
        };

        return textResult(
          `${actionLabel[result.action] || result.action} for ${params.thread_id}.\nNext phase: ${result.next_phase}`,
          { ...result },
        );
      } catch (err) {
        return textResult(`Failed to submit Ripple decision: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
