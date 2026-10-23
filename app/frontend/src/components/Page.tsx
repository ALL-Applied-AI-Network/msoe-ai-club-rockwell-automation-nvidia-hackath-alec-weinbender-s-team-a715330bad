import type { ReactNode } from "react";
import { Link, NavLink } from "react-router";
import { useMeta } from "../backend/queries";
import { CAVEATS } from "../caveats";
import { Banner } from "./Banner";
import { Icon } from "./Icon";
import { ErrorState } from "./States";
import { StatusBar } from "./StatusBar";
import styles from "./Page.module.css";

// The experiments list is home, so the logo and Experiments both go there. New experiment is its main button, not a nav
// item.
const NAV = [
  { to: "/", label: "Experiments", end: true },
  { to: "/parts", label: "Parts" },
  { to: "/validation", label: "Validation" },
  { to: "/cells", label: "Cells" },
];

type PageProps = {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode; // at the right of the title, e.g. the page's main button
  children: ReactNode;
};

/** The page shell every page sits in: the top bar (navigation), the demo-data notice, the page's title, the content
 *  width and the status bar (the GPU and the sim). When the API doesn't answer, it says so instead of an empty page. */
export function Page({ title, description, actions, children }: PageProps) {
  const meta = useMeta();
  return (
    <>
      <header className={styles.topbar}>
        <div className={styles.bar}>
          <Link to="/" className={styles.brand}>
            <span className={styles.mark}>
              <Icon name="gripper" />
            </span>
            Auto-Grasp
          </Link>
          <nav className={styles.nav} aria-label="Main">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => [styles.link, isActive && styles.current].filter(Boolean).join(" ")}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      {meta.data?.demo_data && (
        <Banner tone="warn" strip>
          {CAVEATS.demoData}
        </Banner>
      )}
      <main className={styles.content}>
        {meta.isError ? (
          <ErrorState
            title="Can't reach the backend"
            message="Start it from the repo root: uv run --package backend uvicorn api.main:app --port 8000"
            onRetry={() => meta.refetch()}
          />
        ) : (
          <>
            {(title || actions) && (
              <div className={styles.heading}>
                <div>
                  {title && <h1 className={styles.title}>{title}</h1>}
                  {description && <p className={styles.description}>{description}</p>}
                </div>
                {actions && <div className={styles.actions}>{actions}</div>}
              </div>
            )}
            {children}
          </>
        )}
      </main>
      <StatusBar />
    </>
  );
}
