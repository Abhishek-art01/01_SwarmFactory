/**
 * FileTree
 *
 * Displays the project file tree in real time as the swarm writes files.
 * Files are grouped into a virtual directory hierarchy derived from their paths.
 * Newly-written files flash briefly with a cyan highlight so the user can
 * see what just landed.
 *
 * Accepts the `files` array from useSwarm (WrittenFile[]).
 */

import { useState, useEffect, useRef } from "react";
import { WrittenFile } from "../hooks/useSwarm";

// ─── Tree node types ──────────────────────────────────────────────────────────

interface FileNode {
  type: "file";
  name: string;
  path: string;
  language: string;
  size: number;
  writtenAt: string;
}

interface DirNode {
  type: "dir";
  name: string;
  children: TreeNode[];
}

type TreeNode = FileNode | DirNode;

// ─── Build tree from flat file list ──────────────────────────────────────────

/**
 * What does this do?
 * Converts a flat list of WrittenFile paths into a nested DirNode / FileNode tree.
 */
function buildTree(files: WrittenFile[]): DirNode {
  const root: DirNode = { type: "dir", name: "root", children: [] };

  for (const file of files) {
    const parts = file.path.split("/").filter(Boolean);
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const part = parts[i];
      const isFile = i === parts.length - 1;

      if (isFile) {
        current.children.push({
          type: "file",
          name: part,
          path: file.path,
          language: file.language,
          size: file.size,
          writtenAt: file.writtenAt,
        });
      } else {
        let dir = current.children.find(
          (n): n is DirNode => n.type === "dir" && n.name === part
        );
        if (!dir) {
          dir = { type: "dir", name: part, children: [] };
          current.children.push(dir);
        }
        current = dir;
      }
    }
  }

  // Sort: dirs first, then files, both alphabetically
  const sortChildren = (node: DirNode) => {
    node.children.sort((a, b) => {
      if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    node.children.forEach((c) => {
      if (c.type === "dir") sortChildren(c);
    });
  };
  sortChildren(root);

  return root;
}

// ─── Language icon map ────────────────────────────────────────────────────────

const LANG_ICON: Record<string, string> = {
  typescript: "TS",
  javascript: "JS",
  python: "PY",
  rust: "RS",
  go: "GO",
  html: "HT",
  css: "CS",
  json: "{}",
  yaml: "YM",
  toml: "TM",
  markdown: "MD",
  sh: "SH",
  bash: "SH",
};

/** What does this do? Maps a language string to a 2-letter badge. */
function langBadge(lang: string): string {
  return LANG_ICON[lang.toLowerCase()] ?? "  ";
}

/** What does this do? Formats bytes into a human-readable size string. */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}K`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}M`;
}

// ─── FileRow ─────────────────────────────────────────────────────────────────

/**
 * FileRow
 * Renders a single file line inside the tree.
 */
function FileRow({
  node,
  depth,
  isNew,
  onSelect,
}: {
  node: FileNode;
  depth: number;
  isNew: boolean;
  onSelect: (path: string) => void;
}) {
  // What does this do? Renders one file entry with indent, language badge, name, and size.
  return (
    <button
      type="button"
      onClick={() => onSelect(node.path)}
      className={`w-full flex items-center gap-1.5 px-2 py-0.5 text-left rounded text-[11px] font-mono group
        transition-colors duration-300
        ${isNew ? "bg-cyan-500/10 text-cyan-300" : "text-slate-400 hover:text-slate-200 hover:bg-white/[0.03]"}`}
      style={{ paddingLeft: `${8 + depth * 16}px` }}
    >
      {/* Language badge */}
      <span className="text-[8px] text-slate-700 w-4 flex-shrink-0 text-center">
        {langBadge(node.language)}
      </span>

      {/* File name */}
      <span className="flex-1 truncate">{node.name}</span>

      {/* Size */}
      <span className="text-[9px] text-slate-700 flex-shrink-0">
        {formatSize(node.size)}
      </span>
    </button>
  );
}

// ─── DirRow ───────────────────────────────────────────────────────────────────

/**
 * DirRow
 * A collapsible directory row in the tree.
 */
function DirRow({
  node,
  depth,
  recentPaths,
  onSelect,
}: {
  node: DirNode;
  depth: number;
  recentPaths: Set<string>;
  onSelect: (path: string) => void;
}) {
  const [isOpen, setIsOpen] = useState(true);

  // What does this do? Renders the folder header and its children when expanded.
  return (
    <div>
      <button
        type="button"
        onClick={() => setIsOpen((o) => !o)}
        className="w-full flex items-center gap-1.5 px-2 py-0.5 text-left text-[11px] font-mono text-slate-500 hover:text-slate-300"
        style={{ paddingLeft: `${8 + depth * 16}px` }}
      >
        <span className="text-[9px] select-none">{isOpen ? "▾" : "▸"}</span>
        <span>{node.name}/</span>
      </button>
      {isOpen && (
        <div>
          {node.children.map((child, i) =>
            child.type === "dir" ? (
              <DirRow
                key={i}
                node={child}
                depth={depth + 1}
                recentPaths={recentPaths}
                onSelect={onSelect}
              />
            ) : (
              <FileRow
                key={child.path}
                node={child}
                depth={depth + 1}
                isNew={recentPaths.has(child.path)}
                onSelect={onSelect}
              />
            )
          )}
        </div>
      )}
    </div>
  );
}

// ─── Props ────────────────────────────────────────────────────────────────────

interface FileTreeProps {
  files: WrittenFile[];
  /** Called when the user clicks a file — parent can open it in CodeViewer */
  onFileSelect?: (path: string) => void;
}

// ─── Main component ───────────────────────────────────────────────────────────

export function FileTree({ files, onFileSelect }: FileTreeProps) {
  const tree = buildTree(files);
  const [recentPaths, setRecentPaths] = useState<Set<string>>(new Set());
  const prevLengthRef = useRef(0);

  // When does this run and why?
  // Runs when files array grows. Marks new entries as "recent" for 2 s,
  // then clears the highlight so the flash effect is transient.
  useEffect(() => {
    const newFiles = files.slice(prevLengthRef.current);
    prevLengthRef.current = files.length;

    if (newFiles.length === 0) return;

    const paths = new Set(newFiles.map((f) => f.path));
    setRecentPaths((prev) => new Set([...prev, ...paths]));

    const timer = setTimeout(() => {
      setRecentPaths((prev) => {
        const next = new Set(prev);
        paths.forEach((p) => next.delete(p));
        return next;
      });
    }, 2000);

    return () => clearTimeout(timer);
  }, [files]);

  // What does this do? Delegates file selection to the parent's handler.
  const handleSelect = (path: string) => {
    onFileSelect?.(path);
  };

  return (
    <div className="rounded-lg border border-slate-800/60 bg-[#040b10] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/60">
        <span className="text-[9px] font-mono text-slate-600 uppercase tracking-widest">
          File Tree
        </span>
        <span className="text-[9px] font-mono text-slate-700">
          {files.length} file{files.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Tree body */}
      <div className="py-2 max-h-96 overflow-y-auto">
        {files.length === 0 ? (
          <p className="px-3 py-4 text-[11px] font-mono text-slate-700">
            No files written yet...
          </p>
        ) : (
          tree.children.map((child, i) =>
            child.type === "dir" ? (
              <DirRow
                key={i}
                node={child}
                depth={0}
                recentPaths={recentPaths}
                onSelect={handleSelect}
              />
            ) : (
              <FileRow
                key={child.path}
                node={child}
                depth={0}
                isNew={recentPaths.has(child.path)}
                onSelect={handleSelect}
              />
            )
          )
        )}
      </div>
    </div>
  );
}
