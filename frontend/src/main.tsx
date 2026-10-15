import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { applyPalette, initialPalette } from "./components/theme";
import "./styles.css";

// Before the first paint, so a saved theme never flashes the default first.
applyPalette(initialPalette());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
