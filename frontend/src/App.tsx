/**
 * Phase 1 placeholder root component.
 *
 * Routing (React Router), the AuthContext provider, protected routes, and
 * the real pages (Login, Dashboard, Documents, Chat, ...) are added in
 * Phase 3 onward. This confirms the Vite + React + Tailwind scaffold boots.
 */
function App() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <div className="rounded-xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-2xl font-semibold text-slate-900">EnterpriseIQ</h1>
        <p className="mt-2 text-slate-500">
          Project scaffold is running. Routing, auth, and the full UI are added in later phases.
        </p>
      </div>
    </div>
  );
}

export default App;
