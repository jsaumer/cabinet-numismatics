import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes } from "react-router-dom";

import { applyTheme, initialTheme } from "./components/theme";
import Checklists from "./pages/Checklists";
import Dashboard from "./pages/Dashboard";
import ItemDetail from "./pages/ItemDetail";
import ItemForm from "./pages/ItemForm";
import ItemList from "./pages/ItemList";
import Report from "./pages/Report";

export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">(initialTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  return (
    <>
      <header className="site-header no-print">
        <Link to="/">Cabinet</Link>
        <span className="subtitle">Numismatics — Coin &amp; Paper Money Collection Manager</span>
        <nav>
          <NavLink to="/" end>Collection</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/checklists">Checklists</NavLink>
          <button
            className="theme-toggle"
            title="Toggle dark mode"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
          >
            {theme === "dark" ? "☀" : "🌙"}
          </button>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<ItemList />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/report" element={<Report />} />
          <Route path="/checklists" element={<Checklists />} />
          <Route path="/items/new" element={<ItemForm />} />
          <Route path="/items/:id" element={<ItemDetail />} />
          <Route path="/items/:id/edit" element={<ItemForm />} />
        </Routes>
      </main>
    </>
  );
}
