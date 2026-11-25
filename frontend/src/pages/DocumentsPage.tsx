import { useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import { useApi } from "../api/hooks";
import type { DocStatus, DocumentItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { PermissionsEditor, type PermissionValue } from "../components/PermissionsEditor";
import { Empty, ErrorBanner, PageHead, Skeleton, Spinner, StatusBadge, formatDate, formatSize } from "../components/ui";

const ACCEPT = ".pdf,.docx,.txt,.md,.markdown";
const EXTENSIONS = ["pdf", "docx", "txt", "md", "markdown"];
const MAX_BYTES = 20 * 1024 * 1024;
const isBusy = (s: DocStatus) => s === "PROCESSING" || s === "UPLOADED";

export function UploadForm({ onUploaded }: { onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [department, setDepartment] = useState("");
  const [tags, setTags] = useState("");
  const [perm, setPerm] = useState<PermissionValue>({ visibility: "PUBLIC", roles: [], user_ids: [] });
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const pick = (f: File | undefined) => {
    setError(null);
    if (!f) return;
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    if (!EXTENSIONS.includes(ext)) { setFile(null); return setError("Unsupported file type. Use PDF, DOCX, TXT or Markdown."); }
    if (f.size > MAX_BYTES) { setFile(null); return setError("File is larger than 20 MB."); }
    setFile(f);
    if (!title) setTitle(f.name.replace(/\.[^.]+$/, ""));
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) return;
    if (perm.visibility === "RESTRICTED" && !perm.roles.length && !perm.user_ids.length) {
      return setError("Pick at least one role or person for a restricted document.");
    }
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    form.append("department", department);
    form.append("tags", tags);
    form.append("visibility", perm.visibility);
    form.append("roles", perm.roles.join(","));
    form.append("user_ids", perm.user_ids.join(","));
    setBusy(true);
    setError(null);
    try {
      await api("/api/documents", { method: "POST", body: form });
      setFile(null); setTitle(""); setTags("");
      onUploaded();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card stack" onSubmit={submit} aria-label="Upload document">
      <h2>Upload</h2>
      <div
        className={`dropzone${over ? " over" : ""}`} role="button" tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={(e: DragEvent) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files[0]); }}
      >
        {file
          ? <><strong>{file.name}</strong> <span className="muted">· {formatSize(file.size)}</span></>
          : <>Drop a PDF, DOCX, TXT or Markdown file, or click to choose<div className="mono muted">max 20 MB</div></>}
        <input ref={inputRef} type="file" accept={ACCEPT} hidden data-testid="file-input" onChange={(e) => pick(e.target.files?.[0])} />
      </div>
      <div className="grid grid-2">
        <div><label htmlFor="title">Title</label><input id="title" value={title} onChange={(e) => setTitle(e.target.value)} /></div>
        <div><label htmlFor="department">Department</label><input id="department" value={department} onChange={(e) => setDepartment(e.target.value)} /></div>
      </div>
      <div><label htmlFor="tags">Tags (comma separated)</label><input id="tags" value={tags} onChange={(e) => setTags(e.target.value)} /></div>
      <PermissionsEditor value={perm} onChange={setPerm} />
      <ErrorBanner message={error} />
      <button className="btn accent" disabled={!file || busy}>{busy && <Spinner />} Upload &amp; process</button>
    </form>
  );
}

export function DocumentsPage() {
  const { hasRole } = useAuth();
  const canUpload = hasRole("ADMIN", "MANAGER");
  const [status, setStatus] = useState<DocStatus | "">("");
  const [q, setQ] = useState("");
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (q) params.set("q", q);
  const { data, error, loading, reload } = useApi<DocumentItem[]>(`/api/documents?${params}`, {
    pollMs: (docs) => (docs?.some((d) => isBusy(d.processing_status)) ? 3000 : null), // live status while processing
  });
  const [actionError, setActionError] = useState<string | null>(null);

  const act = async (fn: () => Promise<unknown>) => {
    setActionError(null);
    try { await fn(); void reload(); } catch (e) { setActionError(errorMessage(e)); }
  };

  return (
    <>
      <PageHead eyebrow="Library" title="Documents" />
      <div className={`grid${canUpload ? " split" : ""}`}>
        <div className="stack">
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input aria-label="Filter by title" placeholder="Filter by title" value={q} onChange={(e) => setQ(e.target.value)} />
            <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as DocStatus | "")} style={{ width: 180 }}>
              <option value="">All statuses</option><option value="COMPLETED">Completed</option><option value="PROCESSING">Processing</option>
              <option value="UPLOADED">Uploaded</option><option value="FAILED">Failed</option>
            </select>
          </div>
          <ErrorBanner message={error ?? actionError} />
          {loading && !data ? <Skeleton lines={5} /> : !data?.length ? <Empty>No documents you can access yet.</Empty> : (
            <div className="card flush">
              <table>
                <thead><tr><th>Document</th><th>Status</th><th>Access</th><th /></tr></thead>
                <tbody>
                  {data.map((d) => (
                    <tr key={d.id}>
                      <td>
                        <Link to={`/documents/${d.id}`}><strong>{d.title}</strong></Link>
                        <div className="mono muted">{d.file_type.toUpperCase()} · {formatSize(d.file_size)} · {d.uploader_name} · {formatDate(d.upload_timestamp)}</div>
                        {d.processing_error && <div className="text-danger">{d.processing_error}</div>}
                      </td>
                      <td>
                        <StatusBadge status={d.processing_status} />
                        {d.processing_status === "COMPLETED" && <div className="mono muted">{d.chunk_count} chunks</div>}
                      </td>
                      <td><span className={`badge${d.visibility === "RESTRICTED" ? " accent" : ""}`}>{d.visibility}</span></td>
                      <td className="actions">
                        {d.can_manage && d.processing_status === "FAILED" && (
                          <button className="btn ghost sm" onClick={() => act(() => api(`/api/documents/${d.id}/reprocess`, { method: "POST" }))}>Retry</button>
                        )}{" "}
                        {d.can_manage && (
                          <button className="btn danger sm" onClick={() => confirm(`Delete "${d.title}"? This cannot be undone.`) && act(() => api(`/api/documents/${d.id}`, { method: "DELETE" }))}>Delete</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {canUpload && <UploadForm onUploaded={() => void reload()} />}
      </div>
    </>
  );
}
