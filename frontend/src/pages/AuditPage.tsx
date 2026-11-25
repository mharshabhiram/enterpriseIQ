import { useState } from "react";
import { useApi } from "../api/hooks";
import type { AuditLog, User } from "../api/types";
import { Empty, ErrorBanner, PageHead, Skeleton, formatDate } from "../components/ui";

const ACTIONS = ["", "USER_LOGIN", "DOCUMENT_UPLOADED", "DOCUMENT_DELETED", "DOCUMENT_ACCESSED", "SEARCH_PERFORMED",
  "CHAT_REQUEST", "ROLE_CHANGED", "PERMISSION_CHANGED", "PERMISSION_DENIED"];

export function AuditPage() {
  const [action, setAction] = useState("");
  const { data, error } = useApi<AuditLog[]>(`/api/admin/audit-logs${action ? `?action=${action}` : ""}`);
  const { data: users } = useApi<User[]>("/api/users");
  const names = new Map(users?.map((u) => [u.id, u.name]));

  return (
    <>
      <PageHead eyebrow="Administration" title="Audit log">
        <select aria-label="Filter by action" value={action} onChange={(e) => setAction(e.target.value)} style={{ width: 220 }}>
          {ACTIONS.map((a) => <option key={a} value={a}>{a || "All actions"}</option>)}
        </select>
      </PageHead>
      <ErrorBanner message={error} />
      {!data ? <Skeleton lines={8} /> : data.length === 0 ? <Empty>No events.</Empty> : (
        <div className="card flush">
          <table>
            <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Resource</th><th>Details</th></tr></thead>
            <tbody>
              {data.map((l) => (
                <tr key={l.id}>
                  <td className="mono">{formatDate(l.created_at)}</td>
                  <td>{l.user_id ? names.get(l.user_id) ?? l.user_id.slice(0, 8) : "system"}</td>
                  <td><span className={`badge${l.action === "PERMISSION_DENIED" ? " danger" : ""}`}>{l.action}</span></td>
                  <td className="mono muted">{l.resource_type}{l.resource_id ? ` · ${l.resource_id.slice(0, 8)}` : ""}</td>
                  <td className="mono muted" style={{ maxWidth: 320, wordBreak: "break-word" }}>{Object.keys(l.metadata).length ? JSON.stringify(l.metadata) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
