import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, errorMessage } from "../api/client";
import type { SearchResponse, SearchResult } from "../api/types";
import { Empty, ErrorBanner, Highlight, PageHead, Spinner, formatDate } from "../components/ui";

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [fileType, setFileType] = useState("");
  const [department, setDepartment] = useState("");
  const [tag, setTag] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searched, setSearched] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    if (query.trim().length < 2) return;
    setBusy(true);
    setError(null);
    try {
      const filters = {
        file_types: fileType ? [fileType] : null,
        department: department || null,
        tags: tag ? [tag.toLowerCase()] : null,
        date_from: dateFrom ? new Date(dateFrom).toISOString() : null,
      };
      const res = await api<SearchResponse>("/api/search", { method: "POST", json: { query, filters } });
      setResults(res.results);
      setSearched(query);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <PageHead eyebrow="Semantic search" title="Search by meaning" />
      <form className="card stack" onSubmit={run}>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <input aria-label="Search query" placeholder="e.g. rules for working from home" value={query} onChange={(e) => setQuery(e.target.value)} />
          <button className="btn accent" disabled={busy}>{busy ? <Spinner /> : "Search"}</button>
        </div>
        <div className="grid grid-4">
          <div><label htmlFor="ft">File type</label>
            <select id="ft" value={fileType} onChange={(e) => setFileType(e.target.value)}>
              <option value="">Any</option><option value="pdf">PDF</option><option value="docx">DOCX</option><option value="md">Markdown</option><option value="txt">Text</option>
            </select></div>
          <div><label htmlFor="dept">Department</label><input id="dept" value={department} onChange={(e) => setDepartment(e.target.value)} /></div>
          <div><label htmlFor="tag">Tag</label><input id="tag" value={tag} onChange={(e) => setTag(e.target.value)} /></div>
          <div><label htmlFor="from">Uploaded after</label><input id="from" type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} /></div>
        </div>
      </form>
      <div className="stack" style={{ marginTop: 20 }}>
        <ErrorBanner message={error} />
        {results?.length === 0 && <Empty>No passages matched. Try different words — search works on meaning, not exact text.</Empty>}
        {results?.map((r) => (
          <div className="card stack" key={r.chunk_id} style={{ gap: 6 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <Link to={`/documents/${r.document_id}`}><h3>{r.document_name}</h3></Link>
              <span className="badge accent">{(r.similarity * 100).toFixed(0)}% match</span>
            </div>
            <div className="mono muted">
              {r.file_type.toUpperCase()}{r.page ? ` · page ${r.page}` : ""}{r.section ? ` · ${r.section}` : ""} · {r.uploader_name ?? "unknown"} · {formatDate(r.upload_timestamp)}
              {r.department ? ` · ${r.department}` : ""}
            </div>
            <div className="excerpt"><Highlight text={r.excerpt} query={searched} /></div>
          </div>
        ))}
      </div>
    </>
  );
}
