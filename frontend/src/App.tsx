import { Link, Route, Routes } from "react-router-dom";

import ItemDetail from "./pages/ItemDetail";
import ItemForm from "./pages/ItemForm";
import ItemList from "./pages/ItemList";

export default function App() {
  return (
    <>
      <header className="site-header">
        <Link to="/">Cabinet</Link>
        <span className="subtitle">Numismatics — Coin &amp; Paper Money Collection Manager</span>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<ItemList />} />
          <Route path="/items/new" element={<ItemForm />} />
          <Route path="/items/:id" element={<ItemDetail />} />
          <Route path="/items/:id/edit" element={<ItemForm />} />
        </Routes>
      </main>
    </>
  );
}
