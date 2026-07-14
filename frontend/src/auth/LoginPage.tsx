import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "./AuthContext";

export default function LoginPage() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await login(email, password);
      nav("/chat");
    } catch {
      setErr("Invalid credentials");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form onSubmit={onSubmit} className="bg-white rounded shadow p-6 w-full max-w-sm space-y-3">
        <h1 className="text-xl font-semibold">BeFree — Sign in</h1>
        <input
          type="email" required placeholder="Email"
          value={email} onChange={(e) => setEmail(e.target.value)}
          className="w-full border rounded px-3 py-2"
        />
        <input
          type="password" required placeholder="Password"
          value={password} onChange={(e) => setPassword(e.target.value)}
          className="w-full border rounded px-3 py-2"
        />
        {err && <div className="text-red-600 text-sm">{err}</div>}
        <button
          disabled={busy}
          className="w-full bg-black text-white rounded px-3 py-2 disabled:opacity-50"
        >
          {busy ? "..." : "Sign in"}
        </button>
      </form>
    </div>
  );
}
