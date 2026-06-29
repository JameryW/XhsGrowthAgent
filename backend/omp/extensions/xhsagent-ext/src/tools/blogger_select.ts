/** xhs_blogger_select — select or skip a blogger candidate. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { post } from "../api_client.js";
import { textResult } from "../types.js";

interface BloggerSelectResponse {
  thread_id: string;
  status: string;
  next_phase: string;
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
    user_id: pi.zod.string().optional().describe("Selected blogger user_id (required if not skipping)"),
    nickname: pi.zod.string().optional().describe("Selected blogger nickname"),
    skip: pi.zod.boolean().default(false).describe("Skip blogger selection entirely"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_blogger_select",
    label: "XHS Blogger Select",
    description: "Select a blogger candidate or skip blogger selection in a workflow",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const body: Record<string, unknown> = {
          skip: params.skip,
        };
        if (!params.skip) {
          if (!params.user_id) {
            return textResult("user_id is required when not skipping blogger selection.", undefined, true);
          }
          body.user_id = params.user_id;
          if (params.nickname) body.nickname = params.nickname;
        }

        const result = (await post(`/optimization/blogger-select/${params.thread_id}`, body)) as BloggerSelectResponse;
        return textResult(
          params.skip
            ? `Blogger selection skipped for ${params.thread_id}. Status: ${result.status}, Next: ${result.next_phase}`
            : `Blogger "${params.nickname || params.user_id}" selected for ${params.thread_id}. Status: ${result.status}, Next: ${result.next_phase}`,
          { ...result },
        );
      } catch (err) {
        return textResult(`Failed to select blogger: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
