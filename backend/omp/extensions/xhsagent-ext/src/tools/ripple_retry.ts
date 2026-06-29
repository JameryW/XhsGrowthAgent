/** xhs_ripple_retry — retry Ripple analysis when it previously timed out or failed. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

interface RippleRetryResponse {
  thread_id: string;
  status: string;
  message?: string;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_ripple_retry",
    label: "XHS Ripple Retry",
    description: "Retry Ripple CAS analysis when it previously timed out or returned fallback results",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await post(`/workflow/ripple-retry/${params.thread_id}`)) as RippleRetryResponse;

        if (result.status === "skipped") {
          return textResult(`Ripple retry skipped: ${result.message || "no need to retry"}`, { ...result });
        }

        return textResult(
          `Ripple analysis retry started for ${params.thread_id}. Status: ${result.status}`,
          { ...result },
        );
      } catch (err) {
        return textResult(`Failed to retry Ripple: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
