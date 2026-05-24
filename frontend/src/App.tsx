/**
 * App
 *
 * Root component. Sets up React Router with three routes:
 *   /                  → Home (requirement input)
 *   /dashboard/:jobId  → Dashboard (live mission control)
 *   /output/:jobId     → Output (final generated codebase)
 *
 * Also renders a 404 fallback for unknown routes.
 */

import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import Home from "./pages/Home";
import Dashboard from "./pages/Dashboard";
import Output from "./pages/Output";

// What does this do? Renders a simple 404 page for unmatched routes.
function NotFound() {
  return (
    <div className="min-h-screen bg-[#030810] flex flex-col items-center justify-center text-center px-4">
      <p className="text-6xl font-mono font-bold text-slate-800 mb-4">404</p>
      <p className="text-sm font-mono text-slate-600 mb-6">Page not found</p>
      <Link
        to="/"
        className="text-xs font-mono text-cyan-600 hover:text-cyan-400 border border-cyan-900/40 px-4 py-2 rounded transition-colors"
      >
        ← Home
      </Link>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/dashboard/:jobId" element={<Dashboard />} />
        <Route path="/output/:jobId" element={<Output />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </BrowserRouter>
  );
}
