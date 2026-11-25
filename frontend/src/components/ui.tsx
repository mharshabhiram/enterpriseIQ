import type { ReactNode } from "react";
import type { DocStatus } from "../api/types";

export const Spinner = () => <span className="spinner" aria-label="Loading" />;

export function ErrorBanner({ message }: { message: string | null | undefined }) {
  return message ? <div className="alert" role="alert">{message}</div> : null;
}

export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="stack" aria-busy="true">
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton" style={{ width: `${90 - i * 12}%` }} />)}
    </div>
  );
}

export function PageHead({ eyebrow, title, children }: { eyebrow: string; title: string; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1></div>
      <div className="row">{children}</div>
    </div>
  );
}

const statusTone: Record<DocStatus, string> = { COMPLETED: "ok", PROCESSING: "warn", UPLOADED: "warn", FAILED: "danger" };
export const StatusBadge = ({ status }: { status: DocStatus }) => <span className={`badge ${statusTone[status]}`}>{status}</span>;

export const formatDate = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
export const formatSize = (bytes: number) => (bytes > 1e6 ? `${(bytes / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1e3))} KB`);

/** Highlights query words (4+ letters) inside a search excerpt. */
export function Highlight({ text, query }: { text: string; query: string }) {
  const words = query.toLowerCase().split(/\W+/).filter((w) => w.length > 3);
  if (!words.length) return <>{text}</>;
  const re = new RegExp(`(${words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");
  return <>{text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part))}</>;
}
