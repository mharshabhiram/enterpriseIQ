import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { useParams } from "react-router-dom";
import { api, errorMessage, tokenStore } from "../api/client";
import { useApi } from "../api/hooks";
import type { Chunk, DocumentItem, Permission, Role, SummaryResponse } from "../api/types";
import { PermissionsEditor, type PermissionValue } from "../components/PermissionsEditor";
import { ErrorBanner, PageHead, Skeleton, Spinner, StatusBadge, formatDate, formatSize } from "../components/ui";

export function DocumentDetailPage() {
  const { documentId } = useParams();
  const doc = useApi<DocumentItem>(`/api/documents/${documentId}`, {
    pollMs: (d) => (d && (d.processing_status === "UPLOADED" || d.processing_status === "PROCESSING") ? 3000 : null),
  });
  const d = doc.data;
  const ready = d?.processing_status === "COMPLETED";
  const chunks = useApi<Chunk[]>(ready ? `/api/documents/${documentId}/chunks` : null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [summaryType, setSummaryType] = useState("short");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [perm, setPerm] = useState<PermissionValue | null>(null);
  const [saved, setSaved] = useState(false);
  const canManage = d?.can_manage ?? false;
  const visibility = d?.visibility;

  useEffect(() => {
    if (!canManage || !visibility) return;
    api<Permission[]>(`/api/documents/${documentId}/permissions`)
      .then((ps) => setPerm({
        visibility,
        roles: ps.flatMap((p) => (p.role ? [p.role as Role] : [])),
        user_ids: ps.flatMap((p) => (p.user_id ? [p.user_id] : [])),
      }))
      .catch(() => undefined);
  }, [canManage, visibility, documentId]);

  const summarize = async () => {
    setBusy(true); setError(null);
    try { setSummary(await api<SummaryResponse>(`/api/documents/${documentId}/summarize`, { method: "POST", json: { type: summaryType } })); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  const savePermissions = async () => {
    if (!perm) return;
    setError(null); setSaved(false);
    try { await api(`/api/documents/${documentId}/permissions`, { method: "PUT", json: perm }); setSaved(true); void doc.reload(); }
    catch (e) { setError(errorMessage(e)); }
  };

  const download = async () => {
    const res = await fetch(`/api/documents/${documentId}/download`, { headers: { Authorization: `Bearer ${tokenStore.get()}` } });
    if (!res.ok) return setError("Download failed.");
    const url = URL.createObjectURL(await res.blob());
    Object.assign(document.createElement("a"), { href: url, download: d?.original_filename ?? "document" }).click();
    URL.revokeObjectURL(url);
  };

  if (doc.error) return <ErrorBanner message={doc.error} />;
  if (!d) return <Skeleton lines={6} />;

  return (
    <>
      <PageHead eyebrow={d.file_type.toUpperCase()} title={d.title}>
        <StatusBadge status={d.processing_status} />
        <button className="btn ghost" onClick={download}>Download</button>
      </PageHead>
      <ErrorBanner message={error} />
      <div className="grid split">
        <div className="stack">
          <div className="card stack">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2>Summary</h2>
              <div className="row">
                <select aria-label="Summary type" value={summaryType} onChange={(e) => setSummaryType(e.target.value)} style={{ width: 150 }}>
                  <option value="short">Short</option><option value="detailed">Detailed</option><option value="executive">Executive</option>
                </select>
                <button className="btn accent" disabled={!ready || busy} onClick={summarize}>{busy && <Spinner />} Summarize</button>
              </div>
            </div>
            {!ready && <p className="muted">Available once processing finishes.</p>}
            {summary && (
              <div>
                <div className="mono muted">{summary.strategy} · {summary.sections_processed} section(s)</div>
                <ReactMarkdown>{summary.summary}</ReactMarkdown>
              </div>
            )}
          </div>
          <div className="card stack">
            <h2>Extracted chunks</h2>
            {d.processing_status === "FAILED" && <div className="alert">{d.processing_error}</div>}
            {!ready && d.processing_status !== "FAILED" && <div className="row"><Spinner /> Processing…</div>}
            {chunks.data?.map((c) => (
              <div className="source" key={c.id}>
                <div className="mono muted">#{c.chunk_index + 1}{c.page_number ? ` · page ${c.page_number}` : ""}{c.section ? ` · ${c.section}` : ""}</div>
                <div className="excerpt">{c.chunk_text}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="stack">
          <div className="card stack" style={{ gap: 6 }}>
            <h3>Details</h3>
            <div className="mono muted">Uploaded by {d.uploader_name} · {formatDate(d.upload_timestamp)}</div>
            <div className="mono muted">{formatSize(d.file_size)}{d.page_count ? ` · ${d.page_count} pages` : ""} · {d.chunk_count} chunks</div>
            {d.department && <div>Department: {d.department}</div>}
            {d.tags.length > 0 && <div className="row">{d.tags.map((t) => <span className="badge" key={t}>{t}</span>)}</div>}
            {d.embedding_model && <div className="mono muted">Embedded with {d.embedding_model}</div>}
          </div>
          {canManage && perm && (
            <div className="card stack">
              <h3>Access</h3>
              <PermissionsEditor value={perm} onChange={(v) => { setPerm(v); setSaved(false); }} />
              <button className="btn" onClick={savePermissions}>Save access</button>
              {saved && <div className="mono text-ok">Saved</div>}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
