import { FormEvent, useState } from "react";
import { api } from "../api/client";

type Citation = { tag: string; parent_id: string; document_id: string; filename: string; snippet: string };
type Msg = { role: "user" | "assistant"; text: string; citations?: Citation[]; latency_ms?: number };

export default function ChatPage() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);

  async function ask(e: FormEvent) {
    e.preventDefault();
    if (!q.trim()) return;
    setBusy(true);
    const question = q;
    setQ("");
    setMsgs((m) => [...m, { role: "user", text: question }]);
    try {
      const r = await api.post("/query", { question });
      setMsgs((m) => [
        ...m,
        { role: "assistant", text: r.data.answer, citations: r.data.citations, latency_ms: r.data.latency_ms },
      ]);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", text: `Error: ${e.response?.data?.detail || e.message}` }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto flex flex-col h-[calc(100vh-4rem)]">
      <div className="flex-1 overflow-auto space-y-3 mb-4">
        {msgs.length === 0 && (
          <div className="text-sm text-gray-500">Ask a question about your uploaded documents.</div>
        )}
        {msgs.map((m, i) => (
          <div key={i} className={`p-3 rounded ${m.role === "user" ? "bg-black text-white ml-24" : "bg-white shadow mr-24"}`}>
            <div className="whitespace-pre-wrap">{m.text}</div>
            {m.citations && m.citations.length > 0 && (
              <div className="mt-2 text-xs space-y-1">
                {m.citations.map((c) => (
                  <details key={c.tag} className="border-t pt-1">
                    <summary className="cursor-pointer">
                      <span className="font-mono bg-gray-100 px-1 rounded">[{c.tag}]</span> {c.filename}
                    </summary>
                    <div className="text-gray-600 mt-1">{c.snippet}</div>
                  </details>
                ))}
              </div>
            )}
            {m.latency_ms !== undefined && (
              <div className="mt-1 text-[10px] text-gray-500">{m.latency_ms} ms</div>
            )}
          </div>
        ))}
      </div>
      <form onSubmit={ask} className="flex gap-2">
        <input
          value={q} onChange={(e) => setQ(e.target.value)}
          placeholder="Ask a question…"
          className="flex-1 border rounded px-3 py-2"
        />
        <button disabled={busy} className="bg-black text-white px-4 py-2 rounded disabled:opacity-50">
          {busy ? "…" : "Ask"}
        </button>
      </form>
    </div>
  );
}
