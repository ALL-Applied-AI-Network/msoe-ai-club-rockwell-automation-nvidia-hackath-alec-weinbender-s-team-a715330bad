import type { ReactNode } from "react";
import { Link, NavLink } from "react-router";
import { useCompute, useMeta } from "../backend/queries";
import { CAVEATS } from "../caveats";
import { gpuSummary } from "../gpu";
import { Banner } from "./Banner";
import { SimBadge } from "./Badges";
import { ErrorState } from "./States";
import { ThemeToggle } from "./ThemeToggle";
import styles from "./Page.module.css";

// Overview is home, so the logo goes there too.
const NAV = [
  { to: "/", label: "Overview", end: true },
  { to: "/jobs", label: "Jobs" },
  { to: "/parts", label: "Part Library" },
  { to: "/fingers", label: "Finger Library" },
  { to: "/new", label: "Generate Finger" },
  { to: "/cells", label: "Cells" },
];

type PageProps = {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode; // at the right of the title, e.g. the page's main button
  header?: ReactNode; // a page's own heading, in place of title and actions, across both columns (e.g. a job's)
  rail?: ReactNode; // a right-hand column of panels beside the content, lined up with it top and bottom
  // false: the rail's panels keep their own height and the rail stays in view while the content scrolls (a long page)
  stretch?: boolean;
  children: ReactNode;
};

/** The page shell every page sits in: the top bar (navigation, the GPU, which simulator answers, light or dark), the
 *  demo-data notice, the page's title, and the content, with an optional right-hand rail. When the API doesn't answer,
 *  it says so instead of an empty page. */
export function Page({ title, description, actions, header, rail, stretch = true, children }: PageProps) {
  const meta = useMeta();
  const sim = meta.data?.sim;
  return (
    <>
      <header className={styles.topbar}>
        <div className={styles.bar}>
          <Link to="/" className={styles.brand}>
            <svg className={styles.mark} viewBox="0 0 22 22" aria-hidden="true">
              <path d="M3 4 V18 H8 M19 4 V18 H14" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
              <circle cx="11" cy="11" r="2.6" fill="currentColor" />
            </svg>
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
          <div className={styles.tools}>
            <ComputeLink />
            {sim && <SimBadge backend={sim.badge} />}
            {sim?.badge === "isaac" && sim.url && <code className={styles.url}>{sim.url.replace(/^https?:\/\//, "")}</code>}
            <ThemeToggle />
          </div>
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
            {header}
            {rail ? (
              <div className={`${styles.columns} ${stretch ? styles.stretch : ""}`}>
                <div className={styles.column}>{children}</div>
                <aside className={`${styles.column} ${stretch ? "" : styles.sticky}`}>{rail}</aside>
              </div>
            ) : (
              children
            )}
          </>
        )}
      </main>
    </>
  );
}

/** The GPU in the top bar: its state in a word, with a dot; it opens the GPU page. */
function ComputeLink() {
  const compute = useCompute();
  const gpu = compute.data && gpuSummary(compute.data);
  return (
    <Link to="/gpu" className={styles.compute} title="GPU">
      <span className={`${styles.dot} ${styles[gpu?.tone ?? "neutral"]}`} aria-hidden="true" />
      <span className={styles.computeText}>{gpu?.text ?? "Checking the GPU"}</span>
    </Link>
  );
}
