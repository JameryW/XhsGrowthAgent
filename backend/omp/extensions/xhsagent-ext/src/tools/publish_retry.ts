/** xhs_publish_retry — publish or retry publishing existing workflow content. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

interface PublishRetryResponse {
  thread_id: string;
  status: string;
  message?: string;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID with generated content and a publish result"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_publish_retry",
    label: "XHS Publish Retry",
    description:
      "Publish or retry publishing existing XHS content without restarting the fixed creation workflow.",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await post(
          `/workflow/publish-retry/${params.thread_id}`,
        )) as PublishRetryResponse;

        const lines = [
          `Publish retry — ${params.thread_id}:`,
          `  Status: ${result.status}`,
        ];
        if (result.message) lines.push(`  Message: ${result.message}`);

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to publish: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
