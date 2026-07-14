import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import { api } from "../api/client";

type Me = { user_id: string; tenant_id: string; email: string; role: string };
type Ctx = { me: Me | null; login: (e: string, p: string) => Promise<void>; logout: () => void };

const AuthCtx = createContext<Ctx>({} as Ctx);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);

  useEffect(() => {
    if (localStorage.getItem("token")) {
      api.get("/auth/me").then((r) => setMe(r.data)).catch(() => setMe(null));
    }
  }, []);

  async function login(email: string, password: string) {
    const r = await api.post("/auth/login", { email, password });
    localStorage.setItem("token", r.data.access_token);
    const meR = await api.get("/auth/me");
    setMe(meR.data);
  }

  function logout() {
    localStorage.removeItem("token");
    setMe(null);
    window.location.href = "/login";
  }

  return <AuthCtx.Provider value={{ me, login, logout }}>{children}</AuthCtx.Provider>;
}
