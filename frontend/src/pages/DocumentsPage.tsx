import { useEffect, useState } from "react";
import { api } from "../api/client";

type Doc = { id: string; filename: string; status: string; created_at: string };

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  async function load() { setDocs((await api.get("/documents")).data); }
  useEffect(() => { load(); }, []);
  async function del(id: string) {
    if (!confirm("Delete this document?")) return;
    await api.delete(`/documents/${id}`);
    load();
  }
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h2 className="text-lg font-semibold mb-3">Your documents</h2>
      <div className="bg-white rounded shadow divide-y">
        {docs.map((d) => (
          <div key={d.id} className="flex items-center justify-between p-3">
            <div>
              <div className="font-medium">{d.filename}</div>
              <div className="text-xs text-gray-500">{new Date(d.created_at).toLocaleString()} — {d.status}</div>
            </div>
            <button onClick={() => del(d.id)} className="text-sm text-red-600 hover:underline">Delete</button>
          </div>
        ))}
        {docs.length === 0 && <div className="p-4 text-sm text-gray-500">No documents.</div>}
      </div>
    </div>
  );
}
