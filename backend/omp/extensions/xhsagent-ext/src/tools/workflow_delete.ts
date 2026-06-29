/** xhs_workflow_delete — delete a workflow. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { del } from "../api_client.js";
import { textResult } from "../types.js";

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID to delete"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_delete",
    label: "XHS Workflow Delete",
    description: "Delete a workflow and its data",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        await del(`/workflow/${params.thread_id}`);
        return textResult(`Workflow ${params.thread_id} deleted.`);
      } catch (err) {
        return textResult(`Failed to delete workflow: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
