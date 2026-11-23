import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./index.css";

async function start() {
  // The mock API is only bundled into dev builds with VITE_API_MOCK=true.
  if (import.meta.env.DEV && import.meta.env.VITE_API_MOCK === "true") {
    const { startMockApi } = await import("./mocks/browser");
    await startMockApi();
  }
  const root = document.getElementById("root");
  if (!root) throw new Error("#root element missing from index.html");
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
