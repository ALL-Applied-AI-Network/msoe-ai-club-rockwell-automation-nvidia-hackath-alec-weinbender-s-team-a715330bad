import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api, unwrap } from "../backend/client";
import { StatusBadge } from "./StatusBadge";
import styles from "./Page.module.css";

/** The page shell every page sits in: the header (app name, the sim badge every result carries) and the content width. */
export function Page({ children }: { children: ReactNode }) {
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => unwrap(api.GET("/api/meta")) });
  return (
    <>
      <header className={styles.header}>
        <h1 className={styles.title}>Gripper Finger Designer</h1>
        {meta.data &&
          (meta.data.sim.badge === "mock" ? (
            <StatusBadge tone="warn" label="Mock sim: results are made up" />
          ) : (
            <StatusBadge tone="ok" label="Isaac sim" />
          ))}
        {meta.isError && <StatusBadge tone="bad" label="Backend not reachable" />}
      </header>
      <main className={styles.content}>{children}</main>
    </>
  );
}
