/** xhs_workflow_trigger_analytics — manually trigger analytics after publishing. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

interface TriggerAnalyticsResponse {
  thread_id: string;
  status: string;
  message?: string;
  phase?: string;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID (must have publish result)"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_trigger_analytics",
    label: "XHS Trigger Analytics",
    description: "Manually trigger analytics for a workflow after publishing (when auto-analytics was skipped)",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await post(`/workflow/trigger-analytics/${params.thread_id}`)) as TriggerAnalyticsResponse;

        if (result.status === "error") {
          return textResult(`Cannot trigger analytics: ${result.message || "unknown error"}`, { ...result }, true);
        }
        if (result.status === "completed") {
          return textResult(`Analytics already completed for ${params.thread_id}.`, { ...result });
        }

        return textResult(
          `Analytics triggered for ${params.thread_id}. Phase: ${result.phase || "analyzing"}`,
          { ...result },
        );
      } catch (err) {
        return textResult(`Failed to trigger analytics: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
