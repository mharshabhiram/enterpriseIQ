import { useState, type FormEvent } from "react";
import { api, errorMessage } from "../api/client";
import { useApi } from "../api/hooks";
import type { Role, User } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorBanner, PageHead, Skeleton, formatDate } from "../components/ui";

const ROLES: Role[] = ["EMPLOYEE", "MANAGER", "ADMIN"];

export function UsersPage() {
  const { user: me } = useAuth();
  const { data, error, reload } = useApi<User[]>("/api/users");
  const [actionError, setActionError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "EMPLOYEE" as Role, department: "" });

  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try { await fn(); void reload(); } catch (e) { setActionError(errorMessage(e)); }
  };
  const create = (e: FormEvent) => {
    e.preventDefault();
    void act(async () => {
      await api("/api/users", { method: "POST", json: { ...form, department: form.department || null } });
      setForm({ ...form, name: "", email: "", password: "" });
    });
  };

  return (
    <>
      <PageHead eyebrow="Administration" title="Users & roles" />
      <ErrorBanner message={error ?? actionError} />
      <form className="card grid grid-4" style={{ alignItems: "end", marginBottom: 20 }} onSubmit={create} aria-label="Add user">
        <div><label htmlFor="n">Name</label><input id="n" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div><label htmlFor="e">Email</label><input id="e" type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
        <div><label htmlFor="p">Temporary password</label><input id="p" type="password" minLength={8} required value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
        <div><label htmlFor="r">Role</label><select id="r" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></div>
        <div><label htmlFor="d">Department</label><input id="d" value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></div>
        <div><button className="btn accent">Add user</button></div>
      </form>
      {!data ? <Skeleton lines={5} /> : (
        <div className="card flush">
          <table>
            <thead><tr><th>User</th><th>Role</th><th>Department</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data.map((u) => (
                <tr key={u.id}>
                  <td><strong>{u.name}</strong><div className="mono muted">{u.email} · joined {formatDate(u.created_at)}</div></td>
                  <td>
                    <select aria-label={`Role for ${u.name}`} value={u.role} disabled={u.id === me?.id} style={{ width: 140 }}
                      onChange={(e) => act(() => api(`/api/users/${u.id}`, { method: "PATCH", json: { role: e.target.value } }))}>
                      {ROLES.map((r) => <option key={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>{u.department ?? "—"}</td>
                  <td><span className={`badge ${u.is_active ? "ok" : "danger"}`}>{u.is_active ? "Active" : "Disabled"}</span></td>
                  <td className="actions">
                    {u.id !== me?.id && (
                      <>
                        <button className="btn ghost sm" onClick={() => act(() => api(`/api/users/${u.id}`, { method: "PATCH", json: { is_active: !u.is_active } }))}>
                          {u.is_active ? "Disable" : "Enable"}
                        </button>{" "}
                        <button className="btn danger sm" onClick={() => confirm(`Delete ${u.name}?`) && act(() => api(`/api/users/${u.id}`, { method: "DELETE" }))}>Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
