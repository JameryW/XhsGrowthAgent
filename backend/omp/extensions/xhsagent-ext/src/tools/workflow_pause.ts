/** xhs_workflow_pause — pause a running workflow. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID to pause"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_pause",
    label: "XHS Workflow Pause",
    description: "Pause a running workflow",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        await post(`/workflow/pause/${params.thread_id}`);
        return textResult(`Workflow ${params.thread_id} paused.`);
      } catch (err) {
        return textResult(`Failed to pause: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
