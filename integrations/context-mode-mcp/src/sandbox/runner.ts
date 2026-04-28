import { ChildProcessWithoutNullStreams, spawn } from "node:child_process";
import { mkdtempSync, rmSync, readdirSync, statSync, copyFileSync, chmodSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, parse } from "node:path";
import { randomBytes } from "node:crypto";
import type { SecurityPolicy } from "../utils/types";
import { isCommandAllowed, isPathAllowed } from "../utils/types";
import { clampBytes } from "../utils/timing";

export interface ToolErrorLike {
  code: "INVALID_INPUT" | "DENIED" | "TIMEOUT" | "NOT_FOUND" | "FETCH_FAILED" | "EXEC_FAILED" | "DB_UNAVAILABLE" | "FTS_UNAVAILABLE" | "INTERNAL" | "DEGRADED";
  message: string;
  details?: Record<string, unknown>;
}

export interface ExecutionOutput {
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  killed: boolean;
  pid: number | null;
  duration_ms: number;
  workdir: string;
  fs_bytes_written: number;
}

export interface ExecutionInput {
  language: string;
  code?: string;
  filePath?: string;
  args: string[];
  env: Record<string, string>;
  timeout_ms: number;
  security: SecurityPolicy;
}

interface CommandPlan {
  command: string;
  args: string[];
}

function dirBytes(dir: string): number {
  try {
    let total = 0;
    for (const item of readdirSync(dir, { withFileTypes: true })) {
      const childPath = join(dir, item.name);
      if (item.isDirectory()) total += dirBytes(childPath);
      else total += statSync(childPath).size;
    }
    return total;
  } catch {
    return 0;
  }
}

function readStream(stream: NodeJS.ReadableStream): Promise<string> {
  return new Promise((resolve) => {
    const out: Buffer[] = [];
    stream.on("data", (chunk) => out.push(Buffer.from(chunk)));
    stream.on("end", () => resolve(Buffer.concat(out).toString("utf8")));
    stream.on("error", () => resolve(""));
  });
}

function shellEscape(value: string): string {
  return `'${value.replace(/'/g, "'\\''")}'`;
}

function buildCommand(input: ExecutionInput, sandboxDir: string): CommandPlan {
  const args = input.args || [];
  const lang = input.language;

  if (input.filePath) {
    const base = parse(input.filePath).base || `payload-${randomBytes(4).toString("hex")}`;
    const copied = join(sandboxDir, base);
    if (!isPathAllowed(input.filePath, input.security).allowed) {
      throw { code: "DENIED", message: `path denied: ${input.filePath}` } as ToolErrorLike;
    }
    copyFileSync(input.filePath, copied);

    chmodSync(copied, 0o700);

    if (lang === "python") return { command: "python3", args: [copied, ...args] };
    if (lang === "node") return { command: "node", args: [copied, ...args] };
    if (lang === "bun") return { command: "bun", args: [copied, ...args] };
    if (lang === "ruby") return { command: "ruby", args: [copied, ...args] };
    if (lang === "perl") return { command: "perl", args: [copied, ...args] };
    if (lang === "php") return { command: "php", args: [copied, ...args] };
    if (lang === "go") return { command: "go", args: ["run", copied, ...args] };
    if (lang === "rust") {
      const bin = join(sandboxDir, `ctx-${randomBytes(4).toString("hex")}`);
      return {
        command: "bash",
        args: ["-lc", `rustc ${shellEscape(copied)} -O -o ${shellEscape(bin)} && ${shellEscape(bin)} ${args.map(shellEscape).join(" ")}`],
      };
    }
    if (lang === "r") return { command: "Rscript", args: [copied, ...args] };
    if (lang === "elixir") return { command: "elixir", args: [copied, ...args] };

    return { command: "bash", args: ["-lc", [copied, ...args].map(shellEscape).join(" ")] };
  }

  const source = input.code || "";
  if (lang === "shell") return { command: "bash", args: ["-lc", source] };
  if (lang === "python") return { command: "python3", args: ["-c", source, ...args] };
  if (lang === "node") return { command: "node", args: ["-e", source, ...args] };
  if (lang === "bun") return { command: "bun", args: ["-e", source, ...args] };
  if (lang === "ruby") return { command: "ruby", args: ["-e", source, ...args] };
  if (lang === "perl") return { command: "perl", args: ["-e", source, ...args] };
  if (lang === "php") return { command: "php", args: ["-r", source, ...args] };
  if (lang === "go") {
    const tempSource = join(sandboxDir, `payload-${randomBytes(4).toString("hex")}.go`);
    writeFileSync(tempSource, source);
    return { command: "go", args: ["run", tempSource, ...args] };
  }
  if (lang === "rust") {
    const sourcePath = join(sandboxDir, `payload-${randomBytes(4).toString("hex")}.rs`);
    const binary = join(sandboxDir, `ctx-${randomBytes(4).toString("hex")}`);
    writeFileSync(sourcePath, source);
    return {
      command: "bash",
      args: [
        "-lc",
        `rustc ${shellEscape(sourcePath)} -O -o ${shellEscape(binary)} && ${shellEscape(binary)} ${args.map(shellEscape).join(" ")}`,
      ],
    };
  }
  if (lang === "r") return { command: "Rscript", args: ["-e", source, ...args] };
  if (lang === "elixir") return { command: "elixir", args: ["-e", source, ...args] };

  return { command: "bash", args: ["-lc", source] };
}

export async function runInSandbox(input: ExecutionInput): Promise<{ output: ExecutionOutput; error?: ToolErrorLike }> {
  const started = Date.now();
  const timeoutMs = Math.max(1_000, input.timeout_ms || 30_000);
  const workdir = mkdtempSync(join(tmpdir(), "ctx-mode-"));
  const before = dirBytes(workdir);

  try {
    const plan = buildCommand(input, workdir);

    const commandLine = `${plan.command} ${plan.args.join(" ")}`;
    if (input.language === "shell" && !isCommandAllowed(commandLine, input.security).allowed) {
      return {
        output: {
          stdout: "",
          stderr: "command denied by policy",
          exit_code: 1,
          timed_out: false,
          killed: false,
          pid: null,
          duration_ms: 0,
          workdir,
          fs_bytes_written: 0,
        },
        error: { code: "DENIED", message: "command denied by policy", details: { command: commandLine } },
      };
    }

    const child = spawn(plan.command, plan.args, {
      cwd: workdir,
      env: { ...process.env, ...input.env },
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
    }) as unknown as ChildProcessWithoutNullStreams;

    const exitPromise = new Promise<number | null>((resolve) => {
      child.once("exit", (code) => resolve(typeof code === "number" ? code : null));
      child.once("error", () => resolve(1));
    });

    let timedOut = false;
    let killed = false;
    const timer = setTimeout(() => {
      if (!child.pid) return;
      timedOut = true;
      killed = true;
      try {
        process.kill(-child.pid, "SIGKILL");
      } catch {
        try {
          child.kill("SIGKILL");
        } catch {
          // noop
        }
      }
    }, timeoutMs);

    const [stdout, stderr, code] = await Promise.all([readStream(child.stdout), readStream(child.stderr), exitPromise]);
    clearTimeout(timer);

    const output: ExecutionOutput = {
      stdout,
      stderr,
      exit_code: typeof code === "number" ? code : null,
      timed_out: timedOut,
      killed,
      pid: child.pid ?? null,
      duration_ms: Date.now() - started,
      workdir,
      fs_bytes_written: clampBytes(dirBytes(workdir) - before),
    };

    if (timedOut) {
      return {
        output,
        error: { code: "TIMEOUT", message: `execution exceeded ${timeoutMs}ms`, details: { timeout_ms: timeoutMs } },
      };
    }

    if (output.exit_code !== 0) {
      return {
        output,
        error: {
          code: output.stderr ? "EXEC_FAILED" : "EXEC_FAILED",
          message: output.stderr || `exit code ${output.exit_code}`,
          details: { exit_code: output.exit_code },
        },
      };
    }

    return { output };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      output: {
        stdout: "",
        stderr: message,
        exit_code: 1,
        timed_out: false,
        killed: false,
        pid: null,
        duration_ms: Date.now() - started,
        workdir,
        fs_bytes_written: 0,
      },
      error: err && typeof err === "object" && "code" in err ? (err as ToolErrorLike) : { code: "INTERNAL", message },
    };
  } finally {
    try {
      rmSync(workdir, { force: true, recursive: true });
    } catch {
      // cleanup best-effort
    }
  }
}
