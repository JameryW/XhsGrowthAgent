# Research: oh-my-pi (omp) RPC Protocol

- **Query**: How does oh-my-pi's RPC mode work? CLI flags, NDJSON format, event stream, tool invocation, session management, existing web frontends.
- **Scope**: Internal (installed npm package source code) / mixed (GitHub references)
- **Date**: 2026-06-27

## Findings

### 1. Starting omp in RPC Mode (CLI Flags, Config)

**CLI invocation:**
```bash
omp --mode rpc           # Headless JSON-stdin/stdout protocol
omp --mode rpc-ui        # Same as rpc but with extension UI context enabled (for tools like "ask")
omp --mode acp           # Agent Client Protocol mode (standardized protocol via @agentclientprotocol/sdk)
```

The `--mode` flag accepts: `text` (default interactive TUI), `json`, `rpc`, `acp`, `rpc-ui`.

**Source:** `src/cli/flag-tables.ts:100-103`, `src/cli/args.ts:17`

**Additional CLI flags relevant to RPC:**
- `--provider <provider>` - LLM provider to use
- `--model <modelId>` - Model ID to use
- `--session-dir <path>` - Session directory
- `--cwd <path>` - Working directory
- `--auto-approve` / `--yolo` - Skip tool approvals
- `--no-pty` - Force disable PTY (automatically set in rpc-ui mode)
- `--no-title` - Suppress title updates (automatically set in rpc/rpc-ui/acp modes)

**Environment variables:**
- `PI_RPC_EMIT_TITLE=1` - Opt in to title update events (off by default to reduce noise)
- `PI_NO_PTY=1` - Disable PTY-based bash
- `PI_NO_TITLE=1` - Suppress title

**RPC mode automatically:**
- Sets `PI_NOTIFICATIONS=off` (prevents BEL/OSC terminal sequences from corrupting JSON stdout)
- Applies default setting overrides for `async.enabled`, `async.maxJobs`, `bash.autoBackground.enabled`, `bash.autoBackground.thresholdMs`
- Suppresses piped stdin interpretation (stdin is the command channel, not prompt text)

**Source:** `src/main.ts:1034-1048`, `src/modes/rpc/rpc-mode.ts:372-375`

**Startup sequence:**
1. omp starts with `--mode rpc`
2. Initializes session, extensions, tools
3. Writes `{"type":"ready"}\n` to stdout
4. Enters NDJSON read loop on stdin

**Source:** `src/modes/rpc/rpc-mode.ts:375`

### 2. NDJSON Input Format (Commands on stdin)

Commands are JSON objects, one per line, with a `type` field and optional `id` for correlation.

**Full command type union** (from `src/modes/rpc/rpc-types.ts:27-87`):

```typescript
type RpcCommand =
  // Prompting
  | { id?: string; type: "prompt"; message: string; images?: ImageContent[]; streamingBehavior?: "steer" | "followUp" }
  | { id?: string; type: "steer"; message: string; images?: ImageContent[] }
  | { id?: string; type: "follow_up"; message: string; images?: ImageContent[] }
  | { id?: string; type: "abort" }
  | { id?: string; type: "abort_and_prompt"; message: string; images?: ImageContent[] }
  | { id?: string; type: "new_session"; parentSession?: string }

  // State
  | { id?: string; type: "get_state" }
  | { id?: string; type: "get_available_commands" }
  | { id?: string; type: "set_todos"; phases: TodoPhase[] }
  | { id?: string; type: "set_host_tools"; tools: RpcHostToolDefinition[] }
  | { id?: string; type: "set_host_uri_schemes"; schemes: RpcHostUriSchemeDefinition[] }
  | { id?: string; type: "set_subagent_subscription"; level: RpcSubagentSubscriptionLevel }
  | { id?: string; type: "get_subagents" }
  | { id?: string; type: "get_subagent_messages"; subagentId?: string; sessionFile?: string; fromByte?: number }

  // Model
  | { id?: string; type: "set_model"; provider: string; modelId: string }
  | { id?: string; type: "cycle_model" }
  | { id?: string; type: "get_available_models" }

  // Thinking
  | { id?: string; type: "set_thinking_level"; level: ThinkingLevel }
  | { id?: string; type: "cycle_thinking_level" }

  // Queue modes
  | { id?: string; type: "set_steering_mode"; mode: "all" | "one-at-a-time" }
  | { id?: string; type: "set_follow_up_mode"; mode: "all" | "one-at-a-time" }
  | { id?: string; type: "set_interrupt_mode"; mode: "immediate" | "wait" }

  // Compaction
  | { id?: string; type: "compact"; customInstructions?: string }
  | { id?: string; type: "set_auto_compaction"; enabled: boolean }

  // Retry
  | { id?: string; type: "set_auto_retry"; enabled: boolean }
  | { id?: string; type: "abort_retry" }

  // Bash
  | { id?: string; type: "bash"; command: string }
  | { id?: string; type: "abort_bash" }

  // Session
  | { id?: string; type: "get_session_stats" }
  | { id?: string; type: "export_html"; outputPath?: string }
  | { id?: string; type: "switch_session"; sessionPath: string }
  | { id?: string; type: "branch"; entryId: string }
  | { id?: string; type: "get_branch_messages" }
  | { id?: string; type: "get_last_assistant_text" }
  | { id?: string; type: "set_session_name"; name: string }
  | { id?: string; type: "handoff"; customInstructions?: string }

  // Messages
  | { id?: string; type: "get_messages" }

  // Login
  | { id?: string; type: "get_login_providers" }
  | { id?: string; type: "login"; providerId: string };
```

**Additional input frame types** (not in RpcCommand union but handled on stdin):

- `extension_ui_response` - Response to an extension UI request:
  ```typescript
  | { type: "extension_ui_response"; id: string; value: string }
  | { type: "extension_ui_response"; id: string; confirmed: boolean }
  | { type: "extension_ui_response"; id: string; cancelled: true; timedOut?: boolean }
  ```

- `host_tool_result` - Result of a host tool call:
  ```typescript
  { type: "host_tool_result"; id: string; result: AgentToolResult<unknown>; isError?: boolean }
  ```

- `host_tool_update` - Partial/streaming update for a host tool call:
  ```typescript
  { type: "host_tool_update"; id: string; partialResult: AgentToolResult<unknown> }
  ```

- `host_uri_result` - Result of a host URI request:
  ```typescript
  { type: "host_uri_result"; id: string; content?: string; contentType?: "text/markdown" | "application/json" | "text/plain"; notes?: string[]; immutable?: boolean; isError?: boolean; error?: string }
  ```

**Source:** `src/modes/rpc/rpc-types.ts:27-87, 478-481, 404-416, 453-471`

### 3. Output Event Stream Format (stdout)

All output is NDJSON (one JSON object per line). There are several categories:

#### 3a. Ready Signal
```json
{"type":"ready"}
```
Emitted immediately on startup, before accepting commands.

#### 3b. Command Responses
```typescript
type RpcResponse =
  | { id?: string; type: "response"; command: "prompt"; success: true; data?: { agentInvoked: boolean } }
  | { id?: string; type: "response"; command: "steer"; success: true }
  | { id?: string; type: "response"; command: "follow_up"; success: true }
  | { id?: string; type: "response"; command: "abort"; success: true }
  | { id?: string; type: "response"; command: "abort_and_prompt"; success: true }
  | { id?: string; type: "response"; command: "new_session"; success: true; data: { cancelled: boolean } }
  | { id?: string; type: "response"; command: "get_state"; success: true; data: RpcSessionState }
  | { id?: string; type: "response"; command: "get_available_commands"; success: true; data: { commands: RpcAvailableSlashCommand[] } }
  | { id?: string; type: "response"; command: "set_todos"; success: true; data: { todoPhases: TodoPhase[] } }
  | { id?: string; type: "response"; command: "set_host_tools"; success: true; data: { toolNames: string[] } }
  | { id?: string; type: "response"; command: "set_host_uri_schemes"; success: true; data: { schemes: string[] } }
  | { id?: string; type: "response"; command: "set_subagent_subscription"; success: true; data: { level: RpcSubagentSubscriptionLevel } }
  | { id?: string; type: "response"; command: "get_subagents"; success: true; data: { subagents: RpcSubagentSnapshot[] } }
  | { id?: string; type: "response"; command: "get_subagent_messages"; success: true; data: RpcSubagentMessagesResult }
  | { id?: string; type: "response"; command: "set_model"; success: true; data: Model }
  | { id?: string; type: "response"; command: "cycle_model"; success: true; data: { model: Model; thinkingLevel; isScoped: boolean } | null }
  | { id?: string; type: "response"; command: "get_available_models"; success: true; data: { models: Model[] } }
  | { id?: string; type: "response"; command: "set_thinking_level"; success: true }
  | { id?: string; type: "response"; command: "cycle_thinking_level"; success: true; data: { level: Effort } | null }
  | { id?: string; type: "response"; command: "set_steering_mode"; success: true }
  | { id?: string; type: "response"; command: "set_follow_up_mode"; success: true }
  | { id?: string; type: "response"; command: "set_interrupt_mode"; success: true }
  | { id?: string; type: "response"; command: "compact"; success: true; data: CompactionResult }
  | { id?: string; type: "response"; command: "set_auto_compaction"; success: true }
  | { id?: string; type: "response"; command: "set_auto_retry"; success: true }
  | { id?: string; type: "response"; command: "abort_retry"; success: true }
  | { id?: string; type: "response"; command: "bash"; success: true; data: BashResult }
  | { id?: string; type: "response"; command: "abort_bash"; success: true }
  | { id?: string; type: "response"; command: "get_session_stats"; success: true; data: SessionStats }
  | { id?: string; type: "response"; command: "export_html"; success: true; data: { path: string } }
  | { id?: string; type: "response"; command: "switch_session"; success: true; data: { cancelled: boolean } }
  | { id?: string; type: "response"; command: "branch"; success: true; data: { text: string; cancelled: boolean } }
  | { id?: string; type: "response"; command: "get_branch_messages"; success: true; data: { messages: Array<{ entryId: string; text: string }> } }
  | { id?: string; type: "response"; command: "get_last_assistant_text"; success: true; data: { text: string | null } }
  | { id?: string; type: "response"; command: "set_session_name"; success: true }
  | { id?: string; type: "response"; command: "handoff"; success: true; data: RpcHandoffResult | null }
  | { id?: string; type: "response"; command: "get_messages"; success: true; data: { messages: AgentMessage[] } }
  | { id?: string; type: "response"; command: "get_login_providers"; success: true; data: { providers: Array<{ id; name; available; authenticated }> } }
  | { id?: string; type: "response"; command: "login"; success: true; data: { providerId: string } }
  // Error (any command can fail):
  | { id?: string; type: "response"; command: string; success: false; error: string };
```

#### 3c. Agent Events (streamed during prompt execution)
These are `AgentEvent` types from `@oh-my-pi/pi-agent-core`:

```typescript
type AgentEvent =
  | { type: "agent_start" }
  | { type: "agent_end"; messages: AgentMessage[]; telemetry?: AgentRunSummary; coverage?: AgentRunCoverage }
  | { type: "turn_start" }
  | { type: "turn_end"; message: AgentMessage; toolResults: ToolResultMessage[] }
  | { type: "message_start"; message: AgentMessage }
  | { type: "message_update"; message: AgentMessage; assistantMessageEvent: AssistantMessageEvent }
  | { type: "message_end"; message: AgentMessage }
  | { type: "tool_execution_start"; toolCallId: string; toolName: string; args: any; intent?: string }
  | { type: "tool_execution_update"; toolCallId: string; toolName: string; args: any; partialResult: any }
  | { type: "tool_execution_end"; toolCallId: string; toolName: string; result: any; isError?: boolean };
```

#### 3d. Session Events (extend AgentEvent)
```typescript
type AgentSessionEvent =
  | AgentEvent  // All of the above
  | { type: "auto_compaction_start"; reason: "threshold"|"overflow"|"idle"|"incomplete"; action: "context-full"|"handoff"|"shake"|"snapcompact" }
  | { type: "auto_compaction_end"; action: string; result: CompactionResult|undefined; aborted: boolean; willRetry: boolean; errorMessage?: string; skipped?: boolean }
  | { type: "auto_retry_start"; attempt: number; maxAttempts: number; delayMs: number; errorMessage: string }
  | { type: "auto_retry_end"; success: boolean; attempt: number; finalError?: string }
  | { type: "retry_fallback_applied"; from: string; to: string; role: string }
  | { type: "retry_fallback_succeeded"; model: string; role: string }
  | { type: "ttsr_triggered"; rules: Rule[] }
  | { type: "todo_reminder"; todos: TodoItem[]; attempt: number; maxAttempts: number }
  | { type: "todo_auto_clear" }
  | { type: "irc_message"; message: CustomMessage }
  | { type: "notice"; level: "info"|"warning"|"error"; message: string; source?: string }
  | { type: "thinking_level_changed"; thinkingLevel: ThinkingLevel|undefined; configured?: ConfiguredThinkingLevel; resolved?: Effort }
  | { type: "goal_updated"; goal: Goal|null; state?: GoalModeState }
```

#### 3e. Extension UI Requests (server -> client)
```typescript
type RpcExtensionUIRequest =
  | { type: "extension_ui_request"; id: string; method: "select"; title: string; options: string[]; timeout?: number }
  | { type: "extension_ui_request"; id: string; method: "confirm"; title: string; message: string; timeout?: number }
  | { type: "extension_ui_request"; id: string; method: "input"; title: string; placeholder?: string; timeout?: number }
  | { type: "extension_ui_request"; id: string; method: "editor"; title: string; prefill?: string; promptStyle?: boolean }
  | { type: "extension_ui_request"; id: string; method: "cancel"; targetId: string }
  | { type: "extension_ui_request"; id: string; method: "notify"; message: string; notifyType?: "info"|"warning"|"error" }
  | { type: "extension_ui_request"; id: string; method: "setStatus"; statusKey: string; statusText: string|undefined }
  | { type: "extension_ui_request"; id: string; method: "setWidget"; widgetKey: string; widgetLines: string[]|undefined; widgetPlacement?: "aboveEditor"|"belowEditor" }
  | { type: "extension_ui_request"; id: string; method: "setTitle"; title: string }
  | { type: "extension_ui_request"; id: string; method: "set_editor_text"; text: string }
  | { type: "extension_ui_request"; id: string; method: "open_url"; url: string; instructions?: string }
```

#### 3f. Host Tool Call Requests (server -> client)
```typescript
interface RpcHostToolCallRequest {
  type: "host_tool_call";
  id: string;
  toolCallId: string;
  toolName: string;
  arguments: Record<string, unknown>;
}

interface RpcHostToolCancelRequest {
  type: "host_tool_cancel";
  id: string;
  targetId: string;
}
```

#### 3g. Host URI Requests (server -> client)
```typescript
interface RpcHostUriRequest {
  type: "host_uri_request";
  id: string;
  operation: "read" | "write";
  url: string;
  content?: string;  // For write operations
}

interface RpcHostUriCancelRequest {
  type: "host_uri_cancel";
  id: string;
  targetId: string;
}
```

#### 3h. Subagent Events
```typescript
interface RpcSubagentLifecycleFrame { type: "subagent_lifecycle"; payload: SubagentLifecyclePayload }
interface RpcSubagentProgressFrame { type: "subagent_progress"; payload: SubagentProgressPayload }
interface RpcSubagentEventFrame { type: "subagent_event"; payload: SubagentEventPayload }
```

#### 3i. Other output frames
- `{ type: "available_commands_update"; commands: RpcAvailableSlashCommand[] }` - When slash command metadata changes
- `{ type: "prompt_result"; id?: string; agentInvoked: boolean }` - When a prompt resolves as local-only (no agent turn)
- `{ type: "command_output"; text: string }` - Output from ACP builtin slash commands
- `{ type: "session_info_update"; title: string; sessionId: string }` - Session name changes
- `{ type: "config_update"; model: Model; thinkingLevel: ThinkingLevel }` - Model config changes
- `{ type: "extension_error"; extensionPath: string; event: string; error: string }` - Extension runtime errors

**Source:** `src/modes/rpc/rpc-types.ts` (entire file), `src/modes/rpc/rpc-mode.ts:684-1100`

### 4. How Tools/Commands Are Invoked Through RPC

#### Built-in Tools (read, bash, edit, write, grep, find, lsp, etc.)
Built-in tools are handled internally by the agent. When a prompt triggers a tool call, the agent:
1. Emits `tool_execution_start` event on stdout
2. Executes the tool internally
3. Emits `tool_execution_update` events (for streaming results)
4. Emits `tool_execution_end` event on stdout

The RPC host does NOT need to handle built-in tool execution.

#### Host Tools (custom tools registered by the RPC host)
The RPC host can register custom tools that the agent can call, but whose execution is delegated back to the host:

1. **Registration:** Host sends `set_host_tools` command with tool definitions:
   ```json
   {"type":"set_host_tools","tools":[{"name":"my_tool","label":"My Tool","description":"Does something","parameters":{...}}]}
   ```

2. **Agent invokes tool:** The agent decides to call the host tool. The RPC server emits:
   ```json
   {"type":"host_tool_call","id":"abc123","toolCallId":"tc_456","toolName":"my_tool","arguments":{...}}
   ```

3. **Host executes and returns result:**
   ```json
   {"type":"host_tool_result","id":"abc123","result":{"content":[{"type":"text","text":"result"}]},"isError":false}
   ```

4. **Streaming updates (optional):** Host can send partial results:
   ```json
   {"type":"host_tool_update","id":"abc123","partialResult":{"content":[{"type":"text","text":"partial..."}]}}
   ```

5. **Cancellation:** Server can cancel a pending tool call:
   ```json
   {"type":"host_tool_cancel","id":"def456","targetId":"abc123"}
   ```

#### Host URI Schemes
The host can register custom URI schemes (e.g., `db://`, `notion://`) that the agent's `read` and `write` tools can resolve:

1. **Registration:** Host sends `set_host_uri_schemes`:
   ```json
   {"type":"set_host_uri_schemes","schemes":[{"scheme":"db","description":"Database access","writable":true,"immutable":false}]}
   ```

2. **Agent reads/writes URI:** Server emits request:
   ```json
   {"type":"host_uri_request","id":"xyz","operation":"read","url":"db://users/123"}
   ```

3. **Host returns content:**
   ```json
   {"type":"host_uri_result","id":"xyz","content":"...","contentType":"text/markdown","notes":[],"immutable":false}
   ```

**Source:** `src/modes/rpc/host-tools.ts`, `src/modes/rpc/host-uris.ts`, `src/modes/rpc/rpc-types.ts:379-471`

### 5. Session Management

#### Create Session
- **New session:** Send `{"type":"new_session"}` or `{"type":"new_session","parentSession":"/path/to/parent"}`
  - Response: `{"type":"response","command":"new_session","success":true,"data":{"cancelled":false}}`
  - If `cancelled:true`, an extension vetoed the session change

#### Switch Session
- **Switch to existing:** `{"type":"switch_session","sessionPath":"/path/to/session.jsonl"}`
  - Response: `{"type":"response","command":"switch_session","success":true,"data":{"cancelled":false}}`

#### Branch from Message
- **Branch:** `{"type":"branch","entryId":"entry_123"}`
  - Response: `{"type":"response","command":"branch","success":true,"data":{"text":"original message","cancelled":false}}`

#### Get Session State
- **State query:** `{"type":"get_state"}`
  - Response includes: model, thinkingLevel, isStreaming, isCompacting, steeringMode, followUpMode, interruptMode, sessionFile, sessionId, sessionName, autoCompactionEnabled, messageCount, queuedMessageCount, todoPhases, systemPrompt, dumpTools, contextUsage

#### Get Messages
- **All messages:** `{"type":"get_messages"}` - Returns all `AgentMessage[]`
- **Last assistant text:** `{"type":"get_last_assistant_text"}` - Returns last assistant message text
- **Branch candidates:** `{"type":"get_branch_messages"}` - Returns user messages available for branching

#### Handoff
- **Hand off context:** `{"type":"handoff","customInstructions":"..."}`
  - Response: `{"type":"response","command":"handoff","success":true,"data":{"savedPath":"/path/to/saved"}}`
  - Fails if currently streaming

#### Compaction
- **Manual compact:** `{"type":"compact","customInstructions":"..."}`
- **Auto-compaction toggle:** `{"type":"set_auto_compaction","enabled":true}`

**Source:** `src/modes/rpc/rpc-mode.ts:687-1100`, `src/modes/rpc/rpc-types.ts:93-113`

### 6. Existing Web-Based omp Frontends / Bridges

#### collab-web (Referenced in build scripts)
The package.json prepack script references `../collab-web` as a sibling package:
```
"prepack": "bun --cwd=../collab-web run build:tool-views && ..."
```
This is a web-based collaboration frontend that connects to omp sessions via a WebSocket relay. It uses the **Collab protocol** (`src/collab/`), which is a separate encrypted relay-based protocol for real-time multi-user sessions (host + guests). Not the same as the RPC protocol.

#### Agent Client Protocol (ACP) Mode
`omp --mode acp` uses the standardized `@agentclientprotocol/sdk` (v0.25.0) protocol. ACP is described as "a protocol that standardizes communication between code editors and coding agents." The ACP mode also uses NDJSON stdin/stdout but follows the ACP specification rather than omp's native RPC protocol.

#### RpcClient SDK Class
The package includes a built-in `RpcClient` class (`src/modes/rpc/rpc-client.ts`) that:
- Spawns `omp --mode rpc` as a child process
- Provides a typed TypeScript API for all operations
- Handles ready signal detection, request/response correlation by `id`, event routing
- Supports custom tools via `RpcClientCustomTool` interface
- Provides `waitForIdle()` and `collectEvents()` helpers
- Usage example:
  ```typescript
  const client = new RpcClient({ cwd: "/my/project", customTools: [...] });
  await client.start();
  client.onEvent(event => { /* handle streaming events */ });
  await client.prompt("What files are here?");
  await client.waitForIdle();
  const state = await client.getState();
  client.stop();
  ```

#### SDK API (Programmatic)
The package exports `createAgentSession` for in-process usage without RPC:
```typescript
import { createAgentSession } from "@oh-my-pi/pi-coding-agent";
const { session } = await createAgentSession();
session.subscribe(event => { /* handle events */ });
await session.prompt("Hello");
```

#### No Standalone Web TUI Found
There is no standalone web-based TUI frontend for omp in the installed package. The `collab-web` package is referenced but not installed locally. The omp website is `omp.sh`.

### Files Found

| File Path | Description |
|---|---|
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/modes/rpc/rpc-types.ts` | Complete RPC protocol type definitions (commands, responses, events, host tools/URIs) |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/modes/rpc/rpc-mode.ts` | RPC mode implementation: stdin loop, command handler, event output |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/modes/rpc/rpc-client.ts` | RpcClient SDK class: spawns omp in RPC mode, typed API |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/modes/rpc/host-tools.ts` | Host tool bridge: registers custom tools, handles call/result lifecycle |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/modes/rpc/host-uris.ts` | Host URI bridge: registers custom URI schemes, handles read/write |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/modes/rpc/rpc-subagents.ts` | Subagent event tracking for RPC mode |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/cli/args.ts` | CLI argument parsing, Mode type definition |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/cli/flag-tables.ts` | `--mode` flag handler (line 100) |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/main.ts` | Entry point: RPC mode dispatch (line 1368), setting overrides |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/session/agent-session.ts` | AgentSessionEvent types (line 338), event subscription |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/node_modules/@oh-my-pi/pi-agent-core/src/types.ts` | AgentEvent type definition (line 647) |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/collab/protocol.ts` | Collab protocol (separate from RPC; WebSocket relay, AES-GCM encrypted) |
| `/home/admin/.npm-global/lib/node_modules/@oh-my-pi/pi-coding-agent/src/modes/acp/acp-mode.ts` | ACP mode (Agent Client Protocol) |
| `/home/admin/heuristic-agent-framework/backend/omp/extensions/quantagent-ext/` | Example omp extension (not using RPC) |

### Code Patterns

#### Prompt lifecycle (most important for web TUI):
1. Send `{"type":"prompt","message":"..."}` 
2. Receive `{"type":"response","command":"prompt","success":true}` immediately (ack)
3. Receive streaming events: `agent_start` -> `turn_start` -> `message_start` -> `message_update`(s) -> `message_end` -> possibly `tool_execution_start/end` cycles -> `turn_end` -> `agent_end`
4. The `prompt` response is fire-and-forget; actual content comes via events.

#### Request-Response Correlation:
- Commands include optional `id` field
- Responses echo the same `id`
- The `RpcClient` auto-assigns `req_N` IDs and maps responses to pending promises

#### Bidirectional Host Tools:
- Host registers tools via `set_host_tools` command
- When agent calls a host tool, server emits `host_tool_call` on stdout
- Host sends `host_tool_result` back on stdin
- This enables the agent to use tools that only the host environment can provide

### External References

- [oh-my-pi GitHub](https://github.com/can1357/oh-my-pi) - Monorepo
- [Agent Client Protocol](https://github.com/agentclientprotocol/typescript-sdk) - Standardized editor-agent protocol (ACP mode)
- omp.sh - Project website

## Caveats / Not Found

- **collab-web package not available locally.** It is referenced in the build script but is a separate package in the monorepo. It likely contains a web UI for real-time collaboration but could not be inspected.
- **No documentation found for the RPC protocol** beyond the source code itself. There is no README, docs page, or spec document for the RPC mode.
- **The quantagent-ext at `/home/admin/heuristic-agent-framework/backend/omp/`** is an omp extension (using the `ExtensionAPI`), not an RPC host. It does not use the RPC protocol.
- **bun is required.** omp requires bun >=1.3.14 as the runtime. The local installation fails to run (`/usr/bin/env: 'bun': Permission denied`), so live testing was not possible.
- **RpcClient requires bun** - It spawns `bun dist/cli.js --mode rpc` as a subprocess. A Python bridge would need to spawn the process directly and handle the NDJSON protocol manually.
- **ACP mode** was not deeply researched; it follows the `@agentclientprotocol/sdk` specification, which is a separate standardized protocol.
