import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import App from "./App";
import { applyPalette, initialPalette } from "./components/theme";
import "./styles.css";

// Before the first paint, so a saved theme never flashes the default first.
applyPalette(initialPalette());

// One catch-all route holding the whole app: the pages are still declared
// with <Routes> inside App. The data router is here for one thing only, the
// navigation blocker behind the unsaved-changes guard (components/unsaved.ts),
// which React Router offers nowhere else.
const router = createBrowserRouter([{ path: "*", element: <App /> }]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
