import { useEffect, useState } from "react";
import { api } from "../api/client";

type Flag = {
  chunk_id: string;
  filename: string;
  chunk_index: number;
  snippet: string;
  reason: string | null;
  status: string;
  created_at: string;
};

function reasonLabel(reason: string | null): string {
  if (!reason) return "Flagged by the injection classifier";
  if (reason.startsWith("model:")) {
    const score = reason.split(":").pop();
    return `Injection classifier flagged this text (confidence ${Math.round(parseFloat(score || "0") * 100)}%)`;
  }
  if (reason.startsWith("heuristic:")) return "Matched a known injection phrase";
  return reason;
}

export default function AdminReviewPage() {
  const [items, setItems] = useState<Flag[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  async function load() { setItems((await api.get("/admin/flagged")).data); }
  useEffect(() => { load(); }, []);
  async function decide(id: string, decision: "approve" | "reject") {
    setBusy(id);
    try {
      await api.post(`/admin/flagged/${id}/decision`, { decision });
      await load();
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h2 className="text-lg font-semibold mb-1">Flagged chunks (pending review)</h2>
      <p className="text-sm text-gray-600 mb-4">
        These document excerpts look like <b>prompt injection</b> — text that tries to give the
        AI instructions instead of information. They are currently <b>excluded from search results</b>.
        Read each excerpt: <b>Approve</b> if it's legitimate content (it becomes searchable again),
        <b> Reject</b> if it's an attack (it stays excluded, permanently).
      </p>
      <div className="space-y-3">
        {items.map((f) => (
          <div key={f.chunk_id} className="bg-white rounded shadow p-4">
            <div className="flex items-center justify-between gap-3 mb-2">
              <div className="text-sm font-medium">
                {f.filename} <span className="text-xs text-gray-400">(chunk {f.chunk_index})</span>
              </div>
              <div className="flex gap-2 shrink-0">
                <button
                  onClick={() => decide(f.chunk_id, "approve")}
                  disabled={busy === f.chunk_id}
                  title="Legitimate content — include it in search results again"
                  className="bg-green-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                >
                  Approve
                </button>
                <button
                  onClick={() => decide(f.chunk_id, "reject")}
                  disabled={busy === f.chunk_id}
                  title="Confirmed injection — keep it out of search results"
                  className="bg-red-600 text-white px-3 py-1 rounded text-sm disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
            </div>
            <div className="text-xs text-amber-700 mb-2">{reasonLabel(f.reason)}</div>
            <pre className="text-xs bg-gray-50 border rounded p-2 whitespace-pre-wrap max-h-48 overflow-auto">
              {f.snippet || "(chunk text unavailable)"}
            </pre>
            <div className="text-[10px] text-gray-400 mt-2">
              {new Date(f.created_at).toLocaleString()} · <span className="font-mono">{f.chunk_id}</span>
            </div>
          </div>
        ))}
        {items.length === 0 && <div className="text-sm text-gray-500">Nothing to review.</div>}
      </div>
    </div>
  );
}
