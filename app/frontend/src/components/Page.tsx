import type { ReactNode } from "react";
import { Link, NavLink } from "react-router";
import { useCompute, useMeta } from "../backend/queries";
import { CAVEATS } from "../caveats";
import { gpuSummary } from "../gpu";
import { Banner } from "./Banner";
import { SimBadge } from "./Badges";
import { Icon, type IconName } from "./Icon";
import { ProgressBar } from "./ProgressBar";
import { ErrorState } from "./States";
import styles from "./Page.module.css";

// Overview is home, so the logo goes there too.
const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "Overview", icon: "home", end: true },
  { to: "/jobs", label: "Jobs", icon: "list" },
  { to: "/parts", label: "Part Library", icon: "cube" },
  { to: "/fingers", label: "Finger Library", icon: "grid" },
  { to: "/new", label: "Generate Finger", icon: "bolt" },
  { to: "/cells", label: "Cells", icon: "arm" },
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

/** The page shell every page sits in: the sidebar (navigation, and the GPU at its foot), the top bar (which simulator
 *  answers), the demo-data notice, the page's title, and the content, with an optional right-hand rail. When the API
 *  doesn't answer, it says so instead of an empty page. */
export function Page({ title, description, actions, header, rail, stretch = true, children }: PageProps) {
  const meta = useMeta();
  const sim = meta.data?.sim;
  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
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
              <Icon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <ComputeBox />
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          {sim && <SimBadge backend={sim.badge} />}
          {sim?.badge === "isaac" && sim.url && <code className={styles.url}>{sim.url.replace(/^https?:\/\//, "")}</code>}
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
      </div>
    </div>
  );
}

/** The GPU at the foot of the sidebar: its state in a word and a bar; it opens the GPU page. */
function ComputeBox() {
  const compute = useCompute();
  const gpu = compute.data && gpuSummary(compute.data);
  const session = compute.data?.session;
  const level = session?.status === "ready" ? 1 : session?.status === "starting" ? 0.5 : 0;
  return (
    <Link to="/gpu" className={styles.compute}>
      <span className={styles.computeHead}>
        <span className={`${styles.dot} ${styles[gpu?.tone ?? "neutral"]}`} aria-hidden="true" />
        Compute
        <Icon name="chevron" />
      </span>
      <span className={styles.computeText}>{gpu?.text ?? "Checking the GPU"}</span>
      <ProgressBar value={level} label="GPU session" tone={gpu?.tone === "ok" ? "acc" : "active"} />
    </Link>
  );
}
