import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "../App";
import { aiOk, emptyStats, mockFetch, renderWithProviders, userFor } from "./utils";

describe("authentication and protected routes", () => {
  it("redirects signed-out users from a protected page to sign in", async () => {
    mockFetch(() => undefined);
    renderWithProviders(<App />, "/documents");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("signs in, stores the token and shows the dashboard", async () => {
    mockFetch((url, init) => {
      if (url === "/api/auth/login" && init?.method === "POST") return { body: { access_token: "tok", token_type: "bearer", expires_in: 3600 } };
      if (url === "/api/auth/me") return { body: userFor("EMPLOYEE") };
      if (url === "/api/admin/stats") return { body: emptyStats };
      if (url === "/api/health/ai") return aiOk;
    });
    renderWithProviders(<App />, "/login");
    await userEvent.type(screen.getByLabelText("Email"), "employee@x.dev");
    await userEvent.type(screen.getByLabelText("Password"), "secret-pass");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText(/Good to see you, Employee/)).toBeInTheDocument();
    expect(localStorage.getItem("eiq_token")).toBe("tok");
  });

  it("shows the server's error on a wrong password", async () => {
    mockFetch((url) => (url === "/api/auth/login" ? { status: 401, body: { error: { code: "INVALID_CREDENTIALS", message: "Wrong email or password." } } } : undefined));
    renderWithProviders(<App />, "/login");
    await userEvent.type(screen.getByLabelText("Email"), "a@x.dev");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wrong email or password.");
    expect(localStorage.getItem("eiq_token")).toBeNull();
  });

  it("keeps employees out of admin pages and hides admin links", async () => {
    localStorage.setItem("eiq_token", "tok");
    mockFetch((url) => {
      if (url === "/api/auth/me") return { body: userFor("EMPLOYEE") };
      if (url === "/api/admin/stats") return { body: emptyStats };
      if (url === "/api/health/ai") return aiOk;
    });
    renderWithProviders(<App />, "/admin/users");
    expect(await screen.findByText(/Good to see you/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Users & roles" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Audit log" })).not.toBeInTheDocument();
  });

  it("shows admin links to admins", async () => {
    localStorage.setItem("eiq_token", "tok");
    mockFetch((url) => {
      if (url === "/api/auth/me") return { body: userFor("ADMIN") };
      if (url === "/api/admin/stats") return { body: emptyStats };
      if (url === "/api/health/ai") return aiOk;
    });
    renderWithProviders(<App />, "/");
    expect(await screen.findByRole("link", { name: "Audit log" })).toBeInTheDocument();
  });
});
