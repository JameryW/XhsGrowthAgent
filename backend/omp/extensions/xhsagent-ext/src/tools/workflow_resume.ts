/** xhs_workflow_resume — resume a paused workflow. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID to resume"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_workflow_resume",
    label: "XHS Workflow Resume",
    description: "Resume a paused workflow",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        await post(`/workflow/resume/${params.thread_id}`);
        return textResult(`Workflow ${params.thread_id} resumed.`);
      } catch (err) {
        return textResult(`Failed to resume: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
