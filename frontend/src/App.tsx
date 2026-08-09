import { Link, NavLink, Route, Routes } from "react-router-dom";

import Dashboard from "./pages/Dashboard";
import ItemDetail from "./pages/ItemDetail";
import ItemForm from "./pages/ItemForm";
import ItemList from "./pages/ItemList";
import Report from "./pages/Report";

export default function App() {
  return (
    <>
      <header className="site-header no-print">
        <Link to="/">Cabinet</Link>
        <span className="subtitle">Numismatics — Coin &amp; Paper Money Collection Manager</span>
        <nav>
          <NavLink to="/" end>Collection</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<ItemList />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/report" element={<Report />} />
          <Route path="/items/new" element={<ItemForm />} />
          <Route path="/items/:id" element={<ItemDetail />} />
          <Route path="/items/:id/edit" element={<ItemForm />} />
        </Routes>
      </main>
    </>
  );
}
