import { NavLink, Outlet } from "react-router-dom";
import { useApi } from "../api/hooks";
import type { AIHealth } from "../api/types";
import { useAuth } from "../auth/AuthContext";

export function Layout() {
  const { user, logout, hasRole } = useAuth();
  const { data: ai } = useApi<AIHealth>("/api/health/ai");
  const links: [string, string][] = [
    ["/", "Dashboard"],
    ["/chat", "Ask"],
    ["/search", "Search"],
    ["/documents", "Documents"],
    ["/compare", "Compare"],
    ...(hasRole("ADMIN") ? ([["/admin/users", "Users & roles"], ["/admin/audit", "Audit log"]] as [string, string][]) : []),
  ];
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">Enterprise<span>IQ</span></div>
        {links.map(([to, label]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>{label}</NavLink>
        ))}
        <div className="side-foot stack" style={{ gap: 6 }}>
          <div>{user?.name}</div>
          <div className="mono">{user?.role}</div>
          <button className="btn ghost sm" onClick={logout}>Sign out</button>
        </div>
      </aside>
      <main className="main">
        {ai && !(ai.reachable && ai.missing_models.length === 0) && (
          <div className="alert info" style={{ marginBottom: 16 }}>Local AI not ready: {ai.message}</div>
        )}
        <Outlet />
      </main>
    </div>
  );
}
