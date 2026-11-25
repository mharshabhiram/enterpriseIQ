import { Link } from "react-router-dom";
import type { Source } from "../api/types";

export function SourceCard({ source, id }: { source: Source; id?: string }) {
  return (
    <div className="source" id={id}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>
          [S{source.source_number}]{" "}
          {source.document_id ? <Link to={`/documents/${source.document_id}`}>{source.document_name}</Link> : source.document_name}
        </strong>
        <span className="mono muted">
          {source.page ? `p. ${source.page}` : ""}{source.section ? ` · ${source.section}` : ""} · {(source.relevance_score * 100).toFixed(0)}%
        </span>
      </div>
      <div className="excerpt">{source.excerpt}</div>
    </div>
  );
}
