/** xhs_review_approve — approve content in review gate. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";
import type { ReviewResponse } from "../types.js";

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
    feedback: pi.zod.string().optional().describe("Optional approval feedback"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_review_approve",
    label: "XHS Review Approve",
    description: "Approve content in the review gate",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const body: Record<string, unknown> = { decision: "approved" };
        if (params.feedback) body.comments = params.feedback;

        const result = (await post(`/review/submit/${params.thread_id}`, body)) as ReviewResponse;
        return textResult(
          `Content approved for workflow ${params.thread_id}.\nNext phase: ${result.next_phase}`,
        );
      } catch (err) {
        return textResult(`Failed to approve: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
