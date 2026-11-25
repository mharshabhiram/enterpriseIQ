import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";
import { aiOk, mockFetch, renderWithProviders, userFor } from "./utils";

describe("chat UI", () => {
  it("sends a question and renders the cited answer with its sources", async () => {
    localStorage.setItem("eiq_token", "tok");
    const fetchMock = mockFetch((url, init) => {
      if (url === "/api/auth/me") return { body: userFor("EMPLOYEE") };
      if (url === "/api/conversations") return { body: [] };
      if (url === "/api/health/ai") return aiOk;
      if (url === "/api/chat" && init?.method === "POST") {
        const message = {
          id: "m2", conversation_id: "c1", role: "assistant", created_at: "2026-01-01T00:00:00Z",
          content: "Employees receive 25 days of annual leave [S1].",
          sources: [{ source_number: 1, document_id: "d1", document_name: "Leave Policy", page: 2, section: "Annual Leave", chunk_id: "k1", excerpt: "All employees receive 25 days.", relevance_score: 0.82 }],
        };
        return { body: { conversation_id: "c1", answer: message.content, sources: message.sources, message } };
      }
    });
    renderWithProviders(<App />, "/chat");
    await userEvent.type(await screen.findByLabelText("Your question"), "How much leave do I get?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/25 days of annual leave/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "S1" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Leave Policy" })).toHaveAttribute("href", "/documents/d1");
    expect(screen.getByText(/p\. 2 · Annual Leave · 82%/)).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([u]) => u === "/api/chat");
    expect(JSON.parse(call![1]!.body as string)).toEqual({ message: "How much leave do I get?", conversation_id: null });
  });

  it("shows a clear error when the local model is unavailable", async () => {
    localStorage.setItem("eiq_token", "tok");
    mockFetch((url) => {
      if (url === "/api/auth/me") return { body: userFor("EMPLOYEE") };
      if (url === "/api/conversations") return { body: [] };
      if (url === "/api/health/ai") return { body: { reachable: false, missing_models: ["mistral"], message: "Ollama is not reachable." } };
      if (url === "/api/chat") return { status: 503, body: { error: { code: "LLM_UNAVAILABLE", message: "Cannot reach Ollama." } } };
    });
    renderWithProviders(<App />, "/chat");
    expect(await screen.findByText(/Local AI not ready/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Your question"), "Anything?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("Cannot reach Ollama.")).toBeInTheDocument();
  });
});
