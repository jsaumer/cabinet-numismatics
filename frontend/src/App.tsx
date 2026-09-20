import { useEffect, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";

import { MoonIcon, SettingsIcon, SunIcon, TrashIcon } from "./components/icons";
import { applyTheme, initialTheme } from "./components/theme";
import Checklists from "./pages/Checklists";
import Dashboard from "./pages/Dashboard";
import Settings from "./pages/Settings";
import ItemDetail from "./pages/ItemDetail";
import ItemForm from "./pages/ItemForm";
import Import from "./pages/Import";
import ItemList from "./pages/ItemList";
import Pricing from "./pages/Pricing";
import Report from "./pages/Report";
import AddRun from "./pages/AddRun";
import Trash from "./pages/Trash";

/** The dashboard is the home page. Before v0.16.0 the collection list lived at
 * "/", so a "/" link carrying list filters or paging still opens the list. */
function Home() {
  const { search } = useLocation();
  return search ? <Navigate to={`/collection${search}`} replace /> : <Dashboard />;
}

export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">(initialTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <>
      <header className="site-header no-print">
        <Link to="/">Cabinet</Link>
        <span className="subtitle">Numismatics: Coin &amp; Paper Money Collection Manager</span>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/collection">Collection</NavLink>
          <NavLink to="/pricing">Pricing</NavLink>
          <NavLink to="/checklists">Checklists</NavLink>
          <NavLink to="/import">Import</NavLink>
          <NavLink className="nav-icon" to="/trash" title="Trash" aria-label="Trash">
            <TrashIcon />
          </NavLink>
          <NavLink className="nav-icon" to="/settings" title="Settings" aria-label="Settings">
            <SettingsIcon />
          </NavLink>
          <button
            className="theme-toggle nav-icon"
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? <SunIcon /> : <MoonIcon />}
          </button>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/collection" element={<ItemList />} />
          <Route path="/dashboard" element={<Navigate to="/" replace />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/report" element={<Report />} />
          <Route path="/checklists" element={<Checklists />} />
          <Route path="/import" element={<Import />} />
          <Route path="/trash" element={<Trash />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/items/new" element={<ItemForm />} />
          <Route path="/items/run" element={<AddRun />} />
          <Route path="/items/:id" element={<ItemDetail />} />
          <Route path="/items/:id/edit" element={<ItemForm />} />
        </Routes>
      </main>
    </>
  );
}
