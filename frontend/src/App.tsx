import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import LoginPage from "./auth/LoginPage";
import Nav from "./components/Nav";
import AdminReviewPage from "./pages/AdminReviewPage";
import ChatPage from "./pages/ChatPage";
import DocumentsPage from "./pages/DocumentsPage";
import UploadPage from "./pages/UploadPage";

function Protected({ children, admin }: { children: JSX.Element; admin?: boolean }) {
  const { me } = useAuth();
  if (!localStorage.getItem("token")) return <Navigate to="/login" replace />;
  if (!me) return <div className="p-6 text-sm text-gray-500">Loading…</div>;
  if (admin && me.role !== "admin") return <Navigate to="/chat" replace />;
  return children;
}

export default function App() {
  const token = localStorage.getItem("token");
  return (
    <div>
      {token && <Nav />}
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/chat" element={<Protected><ChatPage /></Protected>} />
        <Route path="/upload" element={<Protected><UploadPage /></Protected>} />
        <Route path="/documents" element={<Protected><DocumentsPage /></Protected>} />
        <Route path="/admin" element={<Protected admin><AdminReviewPage /></Protected>} />
        <Route path="*" element={<Navigate to={token ? "/chat" : "/login"} replace />} />
      </Routes>
    </div>
  );
}
