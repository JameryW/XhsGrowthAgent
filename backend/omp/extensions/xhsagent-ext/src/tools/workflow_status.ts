/** xhs_workflow_status — query workflow status with full snapshot. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";
import type { WorkflowStatusResponse } from "../types.js";

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID to check"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_status",
    label: "XHS Workflow Status",
    description: "Query workflow status with full snapshot (phase, progress, data summaries)",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/workflow/status/${params.thread_id}`)) as WorkflowStatusResponse;

        // Build a human-readable status summary
        const lines: string[] = [
          `Workflow Status: ${params.thread_id}`,
          `  Phase: ${result.phase}`,
          `  Status: ${result.status}`,
          `  Progress: ${result.progress_percent}%`,
          `  Current Agent: ${result.current_agent}`,
          `  Next Steps: ${result.next_steps.join(", ") || "none"}`,
        ];

        if (result.error) lines.push(`  Error: ${result.error}`);

        // Data summaries for multi-tenant detection
        const summaries: string[] = [];
        if (result.trend_data && Object.keys(result.trend_data).length > 0) summaries.push("trend_data");
        if (result.content_plan && Object.keys(result.content_plan).length > 0) summaries.push("content_plan");
        if (result.copy_content && Object.keys(result.copy_content).length > 0) summaries.push("copy_content");
        if (result.visual_plan && Object.keys(result.visual_plan).length > 0) summaries.push("visual_plan");
        if (result.publish_result && Object.keys(result.publish_result).length > 0) summaries.push("publish_result");
        if (result.analytics && Object.keys(result.analytics).length > 0) summaries.push("analytics");
        if (summaries.length > 0) lines.push(`  Data: ${summaries.join(", ")}`);

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get status: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
