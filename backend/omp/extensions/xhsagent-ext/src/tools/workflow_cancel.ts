/** xhs_workflow_cancel — cancel a workflow. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID to cancel"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_cancel",
    label: "XHS Workflow Cancel",
    description: "Cancel a workflow",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        await post(`/workflow/cancel/${params.thread_id}`);
        return textResult(`Workflow ${params.thread_id} cancelled.`);
      } catch (err) {
        return textResult(`Failed to cancel: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
