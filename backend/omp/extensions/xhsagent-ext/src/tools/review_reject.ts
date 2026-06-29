/** xhs_review_reject — reject content in review gate with revision notes. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";
import type { ReviewResponse } from "../types.js";

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
    feedback: pi.zod.string().describe("Revision feedback / reason for rejection"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_review_reject",
    label: "XHS Review Reject",
    description: "Reject content at the review gate with revision feedback. Use xhs_review_pending first to see the content.",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await post(`/review/submit/${params.thread_id}`, {
          decision: "needs_revision",
          comments: params.feedback,
        })) as ReviewResponse;
        return textResult(
          `Content rejected for workflow ${params.thread_id}. Revision requested.\nNext phase: ${result.next_phase}`,
        );
      } catch (err) {
        return textResult(`Failed to reject: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
