import { randomUUID } from "node:crypto";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema, type CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import {
  CtxExecuteRequest,
  CtxExecuteFileRequest,
  CtxBatchRequest,
  CtxIndexRequest,
  CtxSearchRequest,
  CtxFetchIndexRequest,
  CtxStatsRequest,
  CtxDoctorRequest,
  CtxUpgradeRequest,
  CtxPurgeRequest,
  CtxDashboardOpenRequest,
  ToolError,
} from "./schemas/context-tools";
import { beginRunMeta, toolError } from "./tools/shared";
import { handleBatchTool, handleDashboardOpenTool, handleDoctorTool, handleFetchIndexTool, handleIndexTool, handlePurgeTool, handleSearchTool, handleStatsTool, handleUpgradeTool } from "./tools/utility-tools";
import { handleExecute, handleExecuteFile } from "./tools/exec-tools";
import { initSchema } from "./db/schema";
import { openSqlBackend } from "./db/adapter";
import { loadSecurityPolicy, resolveSessionContext } from "./utils/types";
import { startLifecycleGuard } from "./utils/lifecycle";

const STARTED_AT = Date.now();

function withRuntimeSchema() {
  return {
    type: "object",
  };
}

const TOOL_MANIFEST = [
  {
    name: "ctx_execute",
    description: "Execute code in a sandboxed temp directory and apply auto-indexing policy when output is large.",
    inputSchema: withRuntimeSchema(CtxExecuteRequest),
  },
  {
    name: "ctx_execute_file",
    description: "Execute an existing source file in a sandboxed temp directory and apply output policy.",
    inputSchema: withRuntimeSchema(CtxExecuteFileRequest),
  },
  {
    name: "ctx_batch",
    description: "Run a small bounded list of shell commands and search operations.",
    inputSchema: withRuntimeSchema(CtxBatchRequest),
  },
  {
    name: "ctx_index",
    description: "Index markdown content into the project context store.",
    inputSchema: withRuntimeSchema(CtxIndexRequest),
  },
  {
    name: "ctx_search",
    description: "Search indexed chunks with FTS/substring fallback and return ranked snippets.",
    inputSchema: withRuntimeSchema(CtxSearchRequest),
  },
  {
    name: "ctx_fetch_index",
    description: "Fetch URL, normalize to markdown and index by policy.",
    inputSchema: withRuntimeSchema(CtxFetchIndexRequest),
  },
  {
    name: "ctx_stats",
    description: "Summarize session or windowed run-byte savings.",
    inputSchema: withRuntimeSchema(CtxStatsRequest),
  },
  {
    name: "ctx_doctor",
    description: "Check runtime hooks/backend/fts/runtime health and degradation state.",
    inputSchema: withRuntimeSchema(CtxDoctorRequest),
  },
  {
    name: "ctx_upgrade",
    description: "Rebuild/reconfigure local context-mode artifacts when requested.",
    inputSchema: withRuntimeSchema(CtxUpgradeRequest),
  },
  {
    name: "ctx_purge",
    description: "Purge session docs/chunks/events and optionally delete DB.",
    inputSchema: withRuntimeSchema(CtxPurgeRequest),
  },
  {
    name: "ctx_dashboard_open",
    description: "Start (or attach to) the local dashboard process.",
    inputSchema: withRuntimeSchema(CtxDashboardOpenRequest),
  },
] as const;

function asToolResponse(response: unknown): CallToolResult {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(response),
      },
    ],
    structuredContent: response,
  };
}

async function bootstrap() {
  const server = new Server(
    {
      name: "context-mode-mcp",
      version: "0.1.0",
    },
    {
      capabilities: {
        tools: {
          listChanged: false,
        },
      },
    },
  );

  const context = resolveSessionContext();
  const security = loadSecurityPolicy(context.project_root);
  const db = await openSqlBackend(context.db_path);
  initSchema(db);

  const lifecycle = startLifecycleGuard(() => {
    try {
      db.close();
    } catch {
      // soft-fail
    }
    process.exit(0);
  });

  server.setRequestHandler(ListToolsRequestSchema, () => ({
    tools: TOOL_MANIFEST,
  }));

  server.setRequestHandler(CallToolRequestSchema, async (request) => {
    const args = request.params.arguments ?? {};
    const tool = request.params.name;
    const requestId = typeof request.params._meta?.requestId === "string" ? request.params._meta.requestId : randomUUID();
    const run = beginRunMeta(context, tool);

    try {
      if (tool === "ctx_execute") {
        const input = CtxExecuteRequest.parse(args);
        const response = await handleExecute({
          db,
          context,
          request: input,
          requestId,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_execute_file") {
        const input = CtxExecuteFileRequest.parse(args);
        const response = await handleExecuteFile({
          db,
          context,
          request: input,
          requestId,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_batch") {
        const input = CtxBatchRequest.parse(args);
        const response = await handleBatchTool({
          db,
          context,
          request: input,
          requestId,
          startTime: STARTED_AT,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_index") {
        const input = CtxIndexRequest.parse(args);
        const response = await handleIndexTool({
          db,
          context,
          request: input,
          requestId,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_search") {
        const input = CtxSearchRequest.parse(args);
        const response = await handleSearchTool({
          db,
          context,
          request: input,
          requestId,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_fetch_index") {
        const input = CtxFetchIndexRequest.parse(args);
        const response = await handleFetchIndexTool({
          db,
          context,
          request: input,
          requestId,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_stats") {
        const input = CtxStatsRequest.parse(args);
        const response = await handleStatsTool({
          db,
          context,
          request: input,
          requestId,
          startTime: STARTED_AT,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_doctor") {
        CtxDoctorRequest.parse(args);
        const response = await handleDoctorTool({
          db,
          context,
          security,
          lifecycle: {
            parentPid: lifecycle.parentPid,
            active: lifecycle.active,
            lastCheckAt: lifecycle.lastCheckAt,
          },
          requestId,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_upgrade") {
        const input = CtxUpgradeRequest.parse(args);
        const response = await handleUpgradeTool({
          db,
          context,
          request: input,
          requestId,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_purge") {
        const input = CtxPurgeRequest.parse(args);
        const response = await handlePurgeTool({
          db,
          context,
          request: input,
          requestId,
        });
        return asToolResponse(response);
      }

      if (tool === "ctx_dashboard_open") {
        const input = CtxDashboardOpenRequest.parse(args);
        const response = await handleDashboardOpenTool({
          context,
          request: input,
          requestId,
        });
        return asToolResponse(response);
      }

      const err = toolError("INVALID_INPUT", `unknown tool: ${tool}`);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ ok: false, tool, error: err, request_id: requestId }),
          },
        ],
        structuredContent: { ok: false, tool, error: err, request_id: requestId },
        isError: true,
      };
    } catch (error) {
      const message =
        error instanceof z.ZodError
          ? `invalid tool input: ${error.issues.map((issue) => issue.message).join(", ")}`
          : error instanceof Error
            ? error.message
            : String(error);
      const parsedError = toolError("INVALID_INPUT", message);

      beginRunMeta(context, tool);
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ ok: false, tool, request_id: requestId, error: parsedError }),
          },
        ],
        structuredContent: {
          ok: false,
          tool,
          request_id: requestId,
          error: parsedError,
        },
        isError: true,
      };
    }
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
}

await bootstrap();
