import { useState } from "react";
import type { Schemas } from "../backend/client";
import { Button } from "./Button";
import { Icon } from "./Icon";
import styles from "./DownloadButton.module.css";

type ExportCheck = Schemas["ExportCheck"];

type DownloadButtonProps = {
  href: string; // the file's URL on the API, e.g. /api/jobs/{id}/designs/D1/cad?format=step
  label: string; // what it downloads, e.g. "STEP of the pair"
  checksUrl?: string; // where to read why it's blocked when the API answers 409, e.g. .../designs/D1/checks
  variant?: "primary" | "secondary";
};

/** Downloads a file from the API under the name the API gives it. A finger whose export checks failed answers 409:
 *  the button then says which check failed and why, under itself, instead of saving an error page. It's never hidden,
 *  so a blocked download is visible rather than missing. */
export function DownloadButton({ href, label, checksUrl, variant = "secondary" }: DownloadButtonProps) {
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState<{ message: string; checks: ExportCheck[] } | null>(null);

  const download = async () => {
    setBusy(true);
    setBlocked(null);
    try {
      const response = await fetch(href);
      if (response.status === 409) {
        setBlocked(await blockedReason(response, checksUrl));
        return;
      }
      if (!response.ok) {
        setBlocked({ message: `The download failed: ${response.status} ${response.statusText}`, checks: [] });
        return;
      }
      save(await response.blob(), fileName(response) ?? href.split("/").pop()?.split("?")[0] ?? "download");
    } catch (error) {
      setBlocked({ message: `The download failed: ${(error as Error).message}`, checks: [] });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.download}>
      <Button variant={variant} size="sm" onClick={() => void download()} disabled={busy}>
        <Icon name="download" />
        {busy ? "Preparing" : label}
      </Button>
      {blocked && (
        <div className={styles.blocked} role="alert">
          <p>{blocked.message}</p>
          {blocked.checks.length > 0 && (
            <ul className={styles.checks}>
              {blocked.checks.map((check) => (
                <li key={check.name}>
                  <strong>{check.name}</strong>: {check.detail}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** Why the API refused: the failed checks when there's a checks URL, else the 409's own message. */
async function blockedReason(response: Response, checksUrl?: string): Promise<{ message: string; checks: ExportCheck[] }> {
  const message = "Blocked: this finger failed an export check, so its files aren't given out.";
  if (checksUrl) {
    const checks = await fetch(checksUrl);
    if (checks.ok) {
      const body = (await checks.json()) as Schemas["ChecksResponse"];
      return { message, checks: body.checks.filter((check) => !check.ok && check.blocking) };
    }
  }
  const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
  return { message: typeof body?.detail === "string" ? body.detail : message, checks: [] };
}

/** The file name from the API's Content-Disposition header: experiment name, ID, design, and _MOCK on mock runs. */
function fileName(response: Response): string | null {
  const header = response.headers.get("content-disposition") ?? "";
  const match = /filename\*?=(?:UTF-8'')?"?([^";]+)"?/i.exec(header);
  return match ? decodeURIComponent(match[1]) : null;
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
