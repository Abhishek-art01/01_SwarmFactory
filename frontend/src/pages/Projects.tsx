import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { createProject, listProjects, Project } from "../lib/api";

export default function Projects() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isCreating, setIsCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    listProjects()
      .then((items) => {
        if (!cancelled) setProjects(items);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load projects");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;

    setIsCreating(true);
    setError(null);
    try {
      const project = await createProject({ name: trimmed, description });
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create project");
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#030810] text-slate-100">
      <header className="border-b border-slate-800/70 bg-[#030810]/90">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <Link to="/" className="text-sm font-mono font-bold text-slate-300 hover:text-cyan-400">
            Swarm<span className="text-cyan-400">Factory</span>
          </Link>
          <span className="text-[10px] font-mono uppercase tracking-[0.24em] text-slate-600">
            Projects
          </span>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-8 grid grid-cols-1 lg:grid-cols-[360px_1fr] gap-6">
        <form onSubmit={handleSubmit} className="rounded-lg border border-slate-800 bg-[#070e17] p-5 space-y-4">
          <div>
            <h1 className="text-lg font-mono font-semibold text-slate-100">New project</h1>
            <p className="text-xs font-mono text-slate-600 mt-1">
              Create a workspace for persistent project chat history.
            </p>
          </div>
          <label className="block">
            <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">Name</span>
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              className="mt-2 w-full rounded border border-slate-800 bg-[#030810] px-3 py-2 text-sm font-mono text-slate-100 outline-none focus:border-cyan-700"
              placeholder="Customer portal"
            />
          </label>
          <label className="block">
            <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">Description</span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              className="mt-2 min-h-24 w-full resize-y rounded border border-slate-800 bg-[#030810] px-3 py-2 text-sm font-mono text-slate-100 outline-none focus:border-cyan-700"
              placeholder="What is this project for?"
            />
          </label>
          <button
            disabled={isCreating || !name.trim()}
            className="w-full rounded border border-cyan-800/70 bg-cyan-950/40 px-4 py-2 text-xs font-mono text-cyan-300 disabled:opacity-40"
          >
            {isCreating ? "Creating..." : "Create Project"}
          </button>
          {error && <p className="text-xs font-mono text-red-400">{error}</p>}
        </form>

        <section className="rounded-lg border border-slate-800 bg-[#070e17]">
          <div className="border-b border-slate-800 px-5 py-4 flex items-center justify-between">
            <h2 className="text-sm font-mono font-semibold text-slate-200">Existing projects</h2>
            <span className="text-[10px] font-mono text-slate-600">{projects.length} total</span>
          </div>
          {isLoading ? (
            <p className="p-5 text-xs font-mono text-slate-500">Loading projects...</p>
          ) : projects.length === 0 ? (
            <p className="p-5 text-xs font-mono text-slate-500">No projects yet. Create one to start a persistent chat.</p>
          ) : (
            <div className="divide-y divide-slate-800">
              {projects.map((project) => (
                <Link
                  key={project.id}
                  to={`/projects/${project.id}`}
                  className="block px-5 py-4 hover:bg-slate-900/40 transition-colors"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-mono text-slate-200">{project.name}</p>
                      <p className="mt-1 truncate text-xs font-mono text-slate-600">
                        {project.description || "No description"}
                      </p>
                    </div>
                    <span className="text-[10px] font-mono text-cyan-600">Open</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
