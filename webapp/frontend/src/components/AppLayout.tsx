import { Link, Outlet, useLocation } from "react-router-dom";

/**
 * App frame shared by every route: a fixed top bar plus a body region that fills the
 * remaining viewport height. The frame itself never scrolls — each page (or the case
 * sidebar + main) scrolls inside `.app-body`, so the chrome stays put like an IDE.
 */
export function AppLayout() {
  const { pathname } = useLocation();
  const onUpload = pathname.startsWith("/upload");

  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark">sd</span>
          <span className="brand-name">sysdx</span>
        </Link>
        <nav className="topnav">
          <Link to="/" className={`topnav-link${pathname === "/" ? " active" : ""}`}>
            Cases
          </Link>
        </nav>
        <div className="topbar-spacer" />
        <Link to="/upload">
          <button className={onUpload ? "secondary" : undefined}>+ New case</button>
        </Link>
      </header>
      <div className="app-body">
        <Outlet />
      </div>
    </div>
  );
}
