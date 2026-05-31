/**
 * main.tsx
 * Vite entry point — mounts the React app into #root.
 */

import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

// What does this do? Bootstraps the React 18 concurrent root.
ReactDOM.createRoot(document.getElementById("root")!).render(
  <App />
);
