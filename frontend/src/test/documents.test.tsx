import { fireEvent, screen } from "@testing-library/react";
import { App } from "../App";
import { aiOk, mockFetch, renderWithProviders, userFor } from "./utils";

const doc = {
  id: "d1", title: "Leave Policy", filename: "leave.md", original_filename: "leave.md", file_type: "md", file_size: 2048,
  uploaded_by: "u-MANAGER", uploader_name: "Manager User", upload_timestamp: "2026-01-02T00:00:00Z", department: "HR", tags: ["hr"],
  description: null, processing_status: "COMPLETED", processing_error: null, page_count: null, chunk_count: 3,
  visibility: "PUBLIC", embedding_model: "nomic-embed-text", can_manage: false,
};

function setup(role: "MANAGER" | "EMPLOYEE") {
  localStorage.setItem("eiq_token", "tok");
  mockFetch((url) => {
    if (url === "/api/auth/me") return { body: userFor(role) };
    if (url.startsWith("/api/documents?")) return { body: [doc] };
    if (url === "/api/health/ai") return aiOk;
  });
  renderWithProviders(<App />, "/documents");
}

describe("documents UI", () => {
  it("lists accessible documents with their status", async () => {
    setup("EMPLOYEE");
    expect(await screen.findByText("Leave Policy")).toBeInTheDocument();
    expect(screen.getByText("COMPLETED")).toBeInTheDocument();
    expect(screen.getByText("3 chunks")).toBeInTheDocument();
  });

  it("hides the upload form and delete buttons from employees", async () => {
    setup("EMPLOYEE");
    await screen.findByText("Leave Policy");
    expect(screen.queryByRole("form", { name: "Upload document" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).not.toBeInTheDocument();
  });

  it("rejects unsupported files before uploading", async () => {
    setup("MANAGER");
    await screen.findByRole("form", { name: "Upload document" });
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [new File(["MZ"], "tool.exe")] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Unsupported file type");
    expect(screen.getByRole("button", { name: /upload & process/i })).toBeDisabled();
  });
});
