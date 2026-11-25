import { useState, type FormEvent } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { errorMessage } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ErrorBanner, Spinner } from "../components/ui";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(name, email, password);
      navigate((location.state as { from?: string } | null)?.from ?? "/", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const title = mode === "login" ? "Sign in" : "Create account";
  return (
    <div className="auth-wrap">
      <form className="card auth-card stack" onSubmit={submit} aria-label={title}>
        <div>
          <div className="eyebrow">EnterpriseIQ</div>
          <h1>{title}</h1>
          <p className="muted">Answers from your organisation's documents — with sources.</p>
        </div>
        <ErrorBanner message={error} />
        {mode === "register" && (
          <div><label htmlFor="name">Full name</label><input id="name" required value={name} onChange={(e) => setName(e.target.value)} /></div>
        )}
        <div><label htmlFor="email">Email</label><input id="email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></div>
        <div>
          <label htmlFor="password">Password</label>
          <input id="password" type="password" required minLength={mode === "register" ? 8 : 1}
            autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button className="btn accent" disabled={busy} type="submit">{busy && <Spinner />} {title}</button>
        <p className="muted">
          {mode === "login" ? <>No account? <Link to="/register">Create one</Link></> : <>Have an account? <Link to="/login">Sign in</Link></>}
        </p>
      </form>
    </div>
  );
}
