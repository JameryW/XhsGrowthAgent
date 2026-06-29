/** xhs_system_health — check system health and configuration status. */
import type { ExtensionAPI, ToolDefinition } from "@oh-my-pi/pi-coding-agent";
import { get } from "../api_client.js";
import { textResult } from "../types.js";

interface HealthResponse {
  status: string;
  version: string;
  checks: {
    llm_providers: { status: string; message: string; providers: Record<string, { status: string; configured: boolean; preview?: string }> };
    xhs_platform: { status: string; configured: boolean; use_browser: boolean };
    ripple_cas: { status: string; configured: boolean; reason?: string };
    database: { status: string; mode: string };
    memory_store: { status: string; backend: string; semantic_index: boolean; embed_model?: string };
  };
}

export default function register(pi: ExtensionAPI) {
  const schema = pi.zod.object({});

  const tool: ToolDefinition<typeof schema> = {
    name: "xhs_system_health",
    label: "XHS System Health",
    description: "Check XhsGrowthAgent system health — LLM providers, XHS platform, Ripple, database, memory store",
    parameters: schema,
    async execute(_id, _params, _signal, _onUpdate, _ctx) {
      try {
        const result = (await get("/system/health")) as HealthResponse;

        const lines = [
          `System Health: ${result.status.toUpperCase()}`,
          `  Version: ${result.version || "unknown"}`,
          "",
          `  LLM Providers: ${result.checks.llm_providers.status}`,
        ];

        // Show each provider status
        const providers = result.checks.llm_providers.providers;
        if (providers) {
          for (const [name, info] of Object.entries(providers)) {
            lines.push(`    ${name}: ${info.configured ? "✓" : "✗"}`);
          }
        }

        lines.push(
          `  XHS Platform: ${result.checks.xhs_platform.status} ${result.checks.xhs_platform.configured ? "(configured)" : "(not configured)"}`,
          `  Ripple CAS: ${result.checks.ripple_cas.status} ${result.checks.ripple_cas.configured ? "(configured)" : "(not configured)"}`,
          `  Database: ${result.checks.database.status} (${result.checks.database.mode})`,
          `  Memory Store: ${result.checks.memory_store.status} ${result.checks.memory_store.semantic_index ? "(semantic index on)" : "(semantic index off)"}${result.checks.memory_store.embed_model ? ` — ${result.checks.memory_store.embed_model}` : ""}`,
        );

        return textResult(lines.join("\n"), { ...result });
      } catch (err) {
        return textResult(`Failed to check health: ${(err as Error).message}`, undefined, true);
      }
    },
  };
  pi.registerTool(tool);
}
