import { Link } from "react-router";
import type { Schemas } from "../../backend/client";
import { Badge } from "../../components/Badge";
import { dateTime } from "../../format";
import { changes } from "./profileFields";
import styles from "./Settings.module.css";

type Saved = Schemas["CellProfileResponse"];

/** Every version of one profile, newest first, each with what changed from the one before. Read-only: old versions
 *  never change, since jobs point at them. */
export function VersionHistory({ versions, viewing }: { versions: Saved[]; viewing: number }) {
  const latestId = versions.at(-1)?.id;
  const newestFirst = versions.map((v, i) => ({ v, before: versions[i - 1] })).reverse();
  return (
    <ol className={styles.versions}>
      {newestFirst.map(({ v, before }) => {
        const lines = before ? changes(before.profile, v.profile) : [];
        return (
          <li key={v.id} className={styles.version}>
            <div className={styles.versionHead}>
              {v.id === viewing ? <span>Version {v.version}</span> : <Link to={`/settings/cells/${v.id}`}>Version {v.version}</Link>}
              {v.id === viewing && <Badge tone="active" label="Open" />}
              {v.id === latestId && <Badge tone="ok" label="Latest" />}
              <span className={styles.versionDate}>{dateTime(v.created)}</span>
            </div>
            {!before && <p className={styles.note}>The first version.</p>}
            {before && lines.length === 0 && <p className={styles.note}>Saved with no changes.</p>}
            {lines.length > 0 && (
              <ul className={styles.list}>
                {lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}
