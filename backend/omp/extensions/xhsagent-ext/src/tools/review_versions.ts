/** xhs_review_versions — get content versions for comparison before review decision. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface VersionEntry {
  version_id: string;
  title: string;
  body: string;
  hashtags: string[];
  image_prompts: string[];
  style_suggestion: string;
  changes_summary: string;
  predicted_score: number;
  created_at: string;
}

interface ReviewVersionsResponse {
  thread_id: string;
  versions: VersionEntry[];
  current: {
    title: string;
    body: string;
    hashtags: string[];
  };
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({
    thread_id: pi.zod.string().describe("Workflow thread ID"),
  });

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_review_versions",
    label: "XHS Review Versions",
    description: "Get all content versions for a workflow to compare before review decision",
    parameters: schema,
    async execute(_id, params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get(`/review/versions/${params.thread_id}`)) as ReviewVersionsResponse;

        if (!result.versions || result.versions.length === 0) {
          return textResult("No content versions available for this workflow.", { thread_id: params.thread_id });
        }

        const lines = [
          `Content Versions — ${params.thread_id} (${result.versions.length} versions):`,
          "",
          `Current: ${result.current?.title || "(no title)"}`,
          "",
          ...result.versions.map((v, i) => {
            return [
              `  ${i + 1}. [${v.version_id}] ${v.changes_summary || "draft"} — ${v.created_at}`,
              `     Title: ${v.title}`,
              `     Body: ${v.body.slice(0, 300)}${v.body.length > 300 ? "..." : ""}`,
            ].join("\n");
          }),
        ];

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to get content versions: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
