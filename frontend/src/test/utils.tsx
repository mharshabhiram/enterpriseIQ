import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";

type Handler = (url: string, init?: RequestInit) => { status?: number; body?: unknown } | undefined;

/** Route fetch calls to a handler; unknown URLs return 404. */
export function mockFetch(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input.toString();
    const res = handler(url, init) ?? { status: 404, body: { error: { code: "NOT_FOUND", message: "Not found" } } };
    const status = res.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(res.body ?? {}), { status, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

export const userFor = (role: "ADMIN" | "MANAGER" | "EMPLOYEE") => ({
  id: `u-${role}`, name: `${role[0]}${role.slice(1).toLowerCase()} User`, email: `${role.toLowerCase()}@x.dev`, role,
  department: null, is_active: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
});

export const aiOk = { body: { reachable: true, missing_models: [], message: "ok" } };

export const emptyStats = {
  total_documents: 0, completed_documents: 0, processing_documents: 0, failed_documents: 0, total_users: 3, total_chunks: 0,
  total_conversations: 0, stale_embedding_documents: 0, top_searches: [], recent_uploads: [], recent_conversations: [], activity_last_14_days: [],
};

export function renderWithProviders(ui: ReactElement, route = "/") {
  return render(<MemoryRouter initialEntries={[route]}><AuthProvider>{ui}</AuthProvider></MemoryRouter>);
}
