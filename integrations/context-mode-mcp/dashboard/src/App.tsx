import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const sampleRows = [
  { name: "ctx_execute", saved: 68 },
  { name: "ctx_search", saved: 91 },
  { name: "ctx_fetch_index", saved: 55 },
  { name: "ctx_batch", saved: 73 },
];

export function App() {
  const rows = useMemo(() => sampleRows, []);

  return (
    <main className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <header className="mb-6">
        <h1 className="text-2xl md:text-3xl font-semibold">Context-Mode MCP Dashboard</h1>
        <p className="text-sm text-slate-300 mt-2">
          Internal-only lane diagnostics for session continuity, execution telemetry, and search indexing.
        </p>
      </header>

      <section className="grid gap-4 md:grid-cols-3 mb-6">
        <article className="card">
          <h2 className="card-title">Session</h2>
          <p>Project hash: <span className="mono">unknown</span></p>
        </article>
        <article className="card">
          <h2 className="card-title">Sandbox</h2>
          <p>Policy: denials are enforced, process group kill on timeout</p>
        </article>
        <article className="card">
          <h2 className="card-title">Storage</h2>
          <p>Cache dir: <span className="mono">~/.claude/context-mode/cache/</span></p>
        </article>
      </section>

      <section className="card">
        <h2 className="card-title mb-3">Indexed savings by tool (%)</h2>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={rows} margin={{ left: 8, right: 12, top: 8, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="saved" fill="#60a5fa" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>
    </main>
  );
}
