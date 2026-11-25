import { Link } from "react-router-dom";
import { useApi } from "../api/hooks";
import type { Stats } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Empty, ErrorBanner, PageHead, Skeleton, StatusBadge, formatDate } from "../components/ui";

export function DashboardPage() {
  const { user, hasRole } = useAuth();
  const { data, error, loading } = useApi<Stats>("/api/admin/stats");

  const byDay = new Map<string, number>();
  data?.activity_last_14_days.forEach((a) => byDay.set(a.day, (byDay.get(a.day) ?? 0) + a.count));
  const days = [...byDay.entries()].sort();
  const max = Math.max(1, ...days.map(([, n]) => n));
  const isAdmin = hasRole("ADMIN");

  return (
    <>
      <PageHead eyebrow={user?.role ?? ""} title={`Good to see you, ${user?.name.split(" ")[0] ?? ""}`}>
        <Link className="btn accent" to="/chat">Ask a question</Link>
        {hasRole("ADMIN", "MANAGER") && <Link className="btn ghost" to="/documents">Upload</Link>}
      </PageHead>
      <ErrorBanner message={error} />
      {loading || !data ? (error ? null : <Skeleton lines={4} />) : (
        <div className="stack">
          <div className="grid grid-4">
            {([
              ["Documents you can access", data.total_documents],
              ["Ready", data.completed_documents],
              ["Processing", data.processing_documents],
              [isAdmin ? "Users" : "Your conversations", isAdmin ? data.total_users : data.total_conversations],
            ] as [string, number][]).map(([label, value]) => (
              <div className="card stat" key={label}><div className="mono muted">{label}</div><div className="value">{value}</div></div>
            ))}
          </div>
          {data.stale_embedding_documents > 0 && (
            <div className="alert info">{data.stale_embedding_documents} document(s) were embedded with a different model and are excluded from search until re-processed.</div>
          )}
          <div className="grid grid-2">
            <div className="card stack">
              <h2>Recent uploads</h2>
              {data.recent_uploads.length === 0 ? <Empty>No documents yet.</Empty> : (
                <table><tbody>
                  {data.recent_uploads.map((d) => (
                    <tr key={d.id}>
                      <td><Link to={`/documents/${d.id}`}>{d.title}</Link><div className="mono muted">{formatDate(d.created_at)}</div></td>
                      <td className="actions"><StatusBadge status={d.status} /></td>
                    </tr>
                  ))}
                </tbody></table>
              )}
            </div>
            <div className="card stack">
              <h2>Recent conversations</h2>
              {data.recent_conversations.length === 0 ? <Empty>Ask your first question.</Empty> : (
                <table><tbody>
                  {data.recent_conversations.map((c) => (
                    <tr key={c.id}><td><Link to={`/chat/${c.id}`}>{c.title}</Link></td><td className="mono muted actions">{formatDate(c.updated_at)}</td></tr>
                  ))}
                </tbody></table>
              )}
            </div>
            <div className="card stack">
              <h2>Top searches</h2>
              {data.top_searches.length === 0 ? <Empty>No searches yet.</Empty> : data.top_searches.map(([q, n]) => (
                <div className="row" key={q} style={{ justifyContent: "space-between" }}><span>{q}</span><span className="badge">{n}</span></div>
              ))}
            </div>
            <div className="card stack">
              <h2>Activity · 14 days</h2>
              {days.length === 0 ? <Empty>No activity yet.</Empty> : (
                <div className="bars">
                  {days.map(([day, n]) => <div key={day} title={`${day}: ${n}`}><div className="bar" style={{ height: `${(n / max) * 110}px` }} /></div>)}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
