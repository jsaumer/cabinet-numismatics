import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";

import { api, ChecklistSummary, CollectionStats } from "../api";

/** The workbench sidebar: the dashboard (the home page) first, then every
 * way into the collection, the checklists, and the pages that read the
 * collection. Counts come from requests other
 * pages already make, refreshed whenever the route changes. */
export function Sidebar() {
  const location = useLocation();
  const [stats, setStats] = useState<CollectionStats | null>(null);
  const [trash, setTrash] = useState<number | null>(null);
  const [lists, setLists] = useState<ChecklistSummary[]>([]);

  useEffect(() => {
    api.collectionStats().then(setStats).catch(() => setStats(null));
    api.listTrash().then((t) => setTrash(t.items.length)).catch(() => setTrash(null));
    api.listChecklists().then(setLists).catch(() => setLists([]));
  }, [location.pathname]);

  const params = new URLSearchParams(location.search);
  const inCollection = location.pathname.startsWith("/collection");
  const status = params.get("status") ?? "";
  const onlyStatus = [...params.keys()].every((k) => k === "status" || k === "sort");
  const viewOn = (s: string) => inCollection && status === s && onlyStatus;
  const pageOn = (path: string) =>
    path === "/" ? location.pathname === "/" : location.pathname.startsWith(path);
  const checklistOn = (id: number) =>
    location.pathname === "/checklists" && params.get("id") === String(id);

  const counts = stats?.counts ?? {};
  const views = [
    { label: "Owned", status: "owned", count: counts.owned },
    { label: "Wish list", status: "wishlist", count: counts.wishlist },
    { label: "Sold", status: "sold", count: counts.sold },
    { label: "Everything", status: "", count: counts.total },
  ];

  return (
    <nav className="sidebar no-print" aria-label="Main">
      <ul className="sidebar-home">
        <li>
          <Link to="/" className={pageOn("/") ? "active" : undefined}
            aria-current={pageOn("/") ? "page" : undefined}>
            Dashboard
          </Link>
        </li>
      </ul>

      <div className="sidebar-group">
        <h2>Collection</h2>
        <ul>
          {views.map((v) => (
            <li key={v.label}>
              <Link
                to={v.status ? `/collection?status=${v.status}` : "/collection"}
                className={viewOn(v.status) ? "active" : undefined}
                aria-current={viewOn(v.status) ? "page" : undefined}
              >
                <span>{v.label}</span>
                {v.count != null && v.count > 0 && <span className="count">{v.count}</span>}
              </Link>
            </li>
          ))}
          <li>
            <Link to="/trash" className={pageOn("/trash") ? "active" : undefined}>
              <span>Trash</span>
              {trash != null && trash > 0 && <span className="count">{trash}</span>}
            </Link>
          </li>
        </ul>
      </div>

      <div className="sidebar-group">
        <h2>
          <Link to="/checklists" className={pageOn("/checklists") && !params.get("id") ? "active" : undefined}>
            Checklists
          </Link>
        </h2>
        <ul>
          {lists.map((list) => (
            <li key={list.id}>
              <Link
                to={`/checklists?id=${list.id}`}
                className={checklistOn(list.id) ? "active" : undefined}
                title={list.name}
              >
                <span className="label">{list.name}</span>
                <span className="count">
                  {list.filled}/{list.total}
                </span>
              </Link>
            </li>
          ))}
          {lists.length === 0 && (
            <li className="sidebar-empty">
              <Link to="/checklists">Start a checklist</Link>
            </li>
          )}
        </ul>
      </div>

      <div className="sidebar-group">
        <h2>Insights</h2>
        <ul>
          <li><Link to="/pricing" className={pageOn("/pricing") ? "active" : undefined}>Pricing</Link></li>
          <li><Link to="/stack" className={pageOn("/stack") ? "active" : undefined}>Stack</Link></li>
          <li><Link to="/report" className={pageOn("/report") ? "active" : undefined}>Insurance report</Link></li>
        </ul>
      </div>

      <div className="sidebar-group sidebar-foot">
        <ul>
          <li><Link to="/import" className={pageOn("/import") ? "active" : undefined}>Import</Link></li>
          <li><Link to="/settings" className={pageOn("/settings") ? "active" : undefined}>Settings</Link></li>
        </ul>
      </div>
    </nav>
  );
}
