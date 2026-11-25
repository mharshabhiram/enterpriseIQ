import { useState } from "react";
import { api, errorMessage } from "../api/client";
import { useApi } from "../api/hooks";
import type { CompareResponse, DocumentItem } from "../api/types";
import { ErrorBanner, PageHead, Spinner } from "../components/ui";

const tone = (t: string) => (t.includes("add") ? "diff-added" : t.includes("remov") ? "diff-removed" : "diff-changed");

export function ComparePage() {
  const { data: docs } = useApi<DocumentItem[]>("/api/documents?status=COMPLETED");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [focus, setFocus] = useState("");
  const [result, setResult] = useState<CompareResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true); setError(null); setResult(null);
    try { setResult(await api<CompareResponse>("/api/documents/compare", { method: "POST", json: { document_a_id: a, document_b_id: b, focus: focus || null } })); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  const picker = (label: string, value: string, set: (v: string) => void) => (
    <div>
      <label htmlFor={label}>{label}</label>
      <select id={label} value={value} onChange={(e) => set(e.target.value)}>
        <option value="">Choose…</option>
        {docs?.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
      </select>
    </div>
  );

  return (
    <>
      <PageHead eyebrow="Analysis" title="Compare documents" />
      <div className="card stack">
        <div className="grid grid-2">{picker("Document A", a, setA)}{picker("Document B", b, setB)}</div>
        <div><label htmlFor="focus">Focus (optional)</label><input id="focus" placeholder="e.g. leave policy changes" value={focus} onChange={(e) => setFocus(e.target.value)} /></div>
        <button className="btn accent" disabled={!a || !b || a === b || busy} onClick={run}>{busy && <Spinner />} Compare</button>
      </div>
      <div className="stack" style={{ marginTop: 20 }}>
        <ErrorBanner message={error} />
        {result && (
          <>
            <div className="card stack">
              <h2>Overview</h2><p>{result.overview}</p>
              {result.key_differences.length > 0 && <ul>{result.key_differences.map((k) => <li key={k}>{k}</li>)}</ul>}
            </div>
            {result.categories.map((c) => (
              <div className="card stack" key={c.name}>
                <h2>{c.name}</h2>
                {c.changes.map((ch, i) => (
                  <div className={`source ${tone(ch.type.toLowerCase())}`} key={i}>
                    <div className="row" style={{ justifyContent: "space-between" }}><strong>{ch.topic}</strong><span className="badge">{ch.type}</span></div>
                    <div className="grid grid-2">
                      <div><div className="mono muted">{result.document_a}</div>{ch.document_a || "—"}</div>
                      <div><div className="mono muted">{result.document_b}</div>{ch.document_b || "—"}</div>
                    </div>
                    {ch.explanation && <p className="muted">{ch.explanation}</p>}
                  </div>
                ))}
              </div>
            ))}
          </>
        )}
      </div>
    </>
  );
}
