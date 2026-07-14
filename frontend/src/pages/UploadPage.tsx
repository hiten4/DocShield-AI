import { useEffect, useState } from "react";
import { api } from "../api/client";

type Doc = { id: string; filename: string; status: string; created_at: string };

export default function UploadPage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  async function load() {
    const r = await api.get<Doc[]>("/documents");
    setDocs(r.data);
  }
  useEffect(() => {
    load();
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, []);

  async function upload(file: File) {
    setBusy(true); setMsg(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.post("/documents", fd, { headers: { "Content-Type": "multipart/form-data" } });
      setMsg(`Uploaded ${file.name} — processing…`);
      load();
    } catch (e: any) {
      setMsg(`Upload failed: ${e.response?.data?.detail || e.message}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <h2 className="text-lg font-semibold">Upload documents</h2>
      <label
        className="block border-2 border-dashed rounded p-8 text-center cursor-pointer hover:bg-white"
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) upload(f); }}
      >
        <input
          type="file" accept=".pdf,.docx,.txt,.xlsx" hidden
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); }}
        />
        {busy ? "Uploading…" : "Drag a PDF/DOCX/TXT/XLSX here or click to select"}
      </label>
      {msg && <div className="text-sm text-gray-700">{msg}</div>}
      <div className="bg-white rounded shadow divide-y">
        {docs.map((d) => (
          <div key={d.id} className="flex justify-between items-center p-3">
            <div>
              <div className="font-medium">{d.filename}</div>
              <div className="text-xs text-gray-500">{new Date(d.created_at).toLocaleString()}</div>
            </div>
            <span className={`text-xs px-2 py-1 rounded ${statusColor(d.status)}`}>{d.status}</span>
          </div>
        ))}
        {docs.length === 0 && <div className="p-4 text-sm text-gray-500">No documents yet.</div>}
      </div>
    </div>
  );
}

function statusColor(s: string) {
  return {
    pending: "bg-gray-100",
    processing: "bg-yellow-100",
    processed: "bg-green-100",
    failed: "bg-red-100",
    quarantined: "bg-red-200",
  }[s] || "bg-gray-100";
}
