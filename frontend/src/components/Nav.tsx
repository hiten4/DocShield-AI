import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export default function Nav() {
  const { me, logout } = useAuth();
  const linkCls = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1.5 rounded ${isActive ? "bg-black text-white" : "hover:bg-gray-100"}`;
  return (
    <nav className="border-b bg-white px-4 py-3 flex gap-2 items-center">
      <Link to="/chat" className="font-semibold mr-2">BeFree</Link>
      <NavLink to="/chat" className={linkCls}>Chat</NavLink>
      <NavLink to="/upload" className={linkCls}>Upload</NavLink>
      <NavLink to="/documents" className={linkCls}>Documents</NavLink>
      {me?.role === "admin" && <NavLink to="/admin" className={linkCls}>Review</NavLink>}
      <span className="ml-auto text-sm text-gray-600">
        {me?.email} <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">{me?.role}</span>
      </span>
      <button onClick={logout} className="text-sm text-red-600 hover:underline">Logout</button>
    </nav>
  );
}
