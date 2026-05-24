/**
 * CodeViewer
 *
 * Displays the content of a generated source file with line numbers and
 * basic syntax-aware token colouring (no heavy library dependency —
 * uses a lightweight regex tokeniser for the most common languages).
 *
 * Accepts a path + content string from the parent (Output page / file click).
 * Shows a copy-to-clipboard button in the header.
 *
 * For a production build you could swap the tokeniser for Prism or Shiki;
 * the component interface stays identical.
 */

import { useState, useCallback } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

interface CodeViewerProps {
  /** Full relative file path, e.g. "src/api/routes.py" */
  path: string;
  /** Raw file content string */
  content: string;
  /** Programming language for syntax hints (e.g. "typescript", "python") */
  language?: string;
}

// ─── Language detection ───────────────────────────────────────────────────────

/**
 * What does this do?
 * Derives the display language from the file extension when `language` prop
 * is not explicitly provided.
 */
function detectLanguage(path: string, hint?: string): string {
  if (hint) return hint.toLowerCase();
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    ts: "typescript", tsx: "typescript",
    js: "javascript", jsx: "javascript",
    py: "python",
    rs: "rust",
    go: "go",
    html: "html",
    css: "css",
    json: "json",
    yaml: "yaml", yml: "yaml",
    md: "markdown",
    sh: "bash", bash: "bash",
    toml: "toml",
  };
  return map[ext] ?? "plaintext";
}

// ─── Tokeniser ────────────────────────────────────────────────────────────────

interface Token {
  type: "keyword" | "string" | "comment" | "number" | "punctuation" | "plain";
  value: string;
}

const KEYWORDS: Record<string, string[]> = {
  typescript: ["const","let","var","function","return","if","else","for","while","class","interface","type","export","import","from","extends","implements","async","await","new","this","true","false","null","undefined","void","string","number","boolean","any","never","readonly"],
  python: ["def","class","return","if","elif","else","for","while","import","from","as","with","try","except","finally","raise","pass","break","continue","True","False","None","and","or","not","in","is","lambda","yield","async","await","self"],
  javascript: ["const","let","var","function","return","if","else","for","while","class","export","import","from","extends","async","await","new","this","true","false","null","undefined"],
  rust: ["fn","let","mut","const","if","else","for","while","match","use","mod","pub","struct","enum","impl","return","true","false","self","super","crate","type","trait","where","async","await"],
  go: ["func","var","const","type","struct","interface","package","import","return","if","else","for","range","switch","case","default","go","chan","map","defer","goroutine","true","false","nil"],
};

/**
 * What does this do?
 * Splits a single line of code into typed tokens for coloring.
 * Uses simple regex patterns — not a full parser, but good enough for
 * the most common constructs in any C-like or Python-like language.
 */
function tokeniseLine(line: string, lang: string): Token[] {
  const tokens: Token[] = [];
  let remaining = line;
  const kw = new Set(KEYWORDS[lang] ?? KEYWORDS["javascript"]);

  while (remaining.length > 0) {
    // Comment
    const commentMatch = remaining.match(/^(\/\/.*|#.*)$/);
    if (commentMatch) {
      tokens.push({ type: "comment", value: commentMatch[1] });
      break;
    }

    // String (double or single quoted, non-greedy)
    const strMatch = remaining.match(/^("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`)/);
    if (strMatch) {
      tokens.push({ type: "string", value: strMatch[1] });
      remaining = remaining.slice(strMatch[1].length);
      continue;
    }

    // Number
    const numMatch = remaining.match(/^(\b\d+\.?\d*\b)/);
    if (numMatch) {
      tokens.push({ type: "number", value: numMatch[1] });
      remaining = remaining.slice(numMatch[1].length);
      continue;
    }

    // Word (keyword or identifier)
    const wordMatch = remaining.match(/^([A-Za-z_$][A-Za-z0-9_$]*)/);
    if (wordMatch) {
      const word = wordMatch[1];
      tokens.push({ type: kw.has(word) ? "keyword" : "plain", value: word });
      remaining = remaining.slice(word.length);
      continue;
    }

    // Punctuation
    const punctMatch = remaining.match(/^([{}()[\];:,.<>=!+\-*/%&|^~?])/);
    if (punctMatch) {
      tokens.push({ type: "punctuation", value: punctMatch[1] });
      remaining = remaining.slice(1);
      continue;
    }

    // Fall through: emit one char as plain
    tokens.push({ type: "plain", value: remaining[0] });
    remaining = remaining.slice(1);
  }

  return tokens;
}

// ─── Token colour map ─────────────────────────────────────────────────────────

const TOKEN_COLOR: Record<Token["type"], string> = {
  keyword:     "text-cyan-400",
  string:      "text-amber-300",
  comment:     "text-slate-600 italic",
  number:      "text-emerald-400",
  punctuation: "text-slate-500",
  plain:       "text-slate-300",
};

// ─── CodeLine ─────────────────────────────────────────────────────────────────

/**
 * CodeLine
 * Renders a single line with a line number and tokenised content.
 */
function CodeLine({ lineNumber, content, language }: {
  lineNumber: number;
  content: string;
  language: string;
}) {
  const tokens = tokeniseLine(content, language);
  return (
    <div className="flex group hover:bg-white/[0.02]">
      {/* Line number gutter */}
      <span className="select-none text-right pr-4 text-[11px] font-mono text-slate-700 w-10 flex-shrink-0 leading-6">
        {lineNumber}
      </span>
      {/* Token content */}
      <span className="flex-1 text-[11px] font-mono leading-6 whitespace-pre">
        {tokens.map((tok, i) => (
          <span key={i} className={TOKEN_COLOR[tok.type]}>
            {tok.value}
          </span>
        ))}
      </span>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export function CodeViewer({ path, content, language }: CodeViewerProps) {
  const lang = detectLanguage(path, language);
  const lines = content.split("\n");
  const [copied, setCopied] = useState(false);

  /**
   * What does this do?
   * Copies the full file content to the system clipboard and shows a brief
   * "Copied!" confirmation in the button.
   */
  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("API error: clipboard write failed →", err);
    }
  }, [content]);

  // What does this do? Extracts just the filename from the full path for display.
  const fileName = path.split("/").pop() ?? path;

  return (
    <div className="rounded-lg border border-slate-800/60 bg-[#040b10] overflow-hidden flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800/60 flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[9px] font-mono text-slate-600 uppercase tracking-widest flex-shrink-0">
            {lang}
          </span>
          <span className="text-[11px] font-mono text-slate-400 truncate" title={path}>
            {fileName}
          </span>
          <span className="text-[10px] font-mono text-slate-700 flex-shrink-0">
            {lines.length} lines
          </span>
        </div>

        {/* Copy button */}
        <button
          type="button"
          onClick={handleCopy}
          className={`text-[10px] font-mono px-2 py-0.5 rounded border transition-all duration-200
            ${copied
              ? "bg-emerald-900/40 border-emerald-600/40 text-emerald-400"
              : "bg-transparent border-slate-700/50 text-slate-500 hover:border-slate-500 hover:text-slate-300"
            }`}
        >
          {copied ? "✓ Copied" : "Copy"}
        </button>
      </div>

      {/* Full path breadcrumb */}
      <div className="px-3 py-1.5 border-b border-slate-800/40 bg-[#030810]">
        <span className="text-[10px] font-mono text-slate-700">{path}</span>
      </div>

      {/* Code body */}
      <div className="overflow-auto flex-1 py-2">
        {lines.map((line, i) => (
          <CodeLine key={i} lineNumber={i + 1} content={line} language={lang} />
        ))}
      </div>
    </div>
  );
}
