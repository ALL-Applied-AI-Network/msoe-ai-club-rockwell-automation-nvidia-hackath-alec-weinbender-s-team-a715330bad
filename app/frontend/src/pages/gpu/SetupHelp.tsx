import type { Schemas } from "../../backend/client";
import { Badge } from "../../components/Badge";
import styles from "./GpuPage.module.css";

type Backend = Schemas["BackendInfo"];

// What each person sets up once, per target, with the SETUP.md section that walks through it (plan 4.3).
const CHECKLISTS = [
  {
    name: "gb10",
    title: "MSOE GB10: free, always on, shared with other teams",
    steps: [
      { text: "Connect the MSOE VPN (GlobalProtect) whenever you use it.", setup: "MSOE VPN" },
      { text: "Add your SSH key to the team account, once.", setup: "Your SSH key on the GB10" },
      {
        text: "In the repo's .env: COMPUTE_BACKENDS with gb10, SIM_BACKEND=http and SIM_URL=http://127.0.0.1:9000. Restart the API.",
        setup: "GPU from the web app",
      },
    ],
  },
  {
    name: "brev",
    title: "Brev: the paid backup, stopped when idle",
    steps: [
      { text: "Join the team's Brev account from the invite.", setup: "Brev account" },
      { text: "On Windows, install WSL and Ubuntu: the Brev CLI only runs there.", setup: "WSL and Ubuntu" },
      { text: "Install the Brev CLI and run brev login in Ubuntu.", setup: "Brev CLI" },
      {
        text: "In the repo's .env: COMPUTE_BACKENDS with brev, and COMPUTE_BREV_WSL=Ubuntu on Windows. Restart the API.",
        setup: "GPU from the web app",
      },
    ],
  },
] as const;

/** The setup checklist per target, short, pointing at SETUP.md. Open until something has connected once. */
export function SetupHelp({ backends, open }: { backends: Backend[]; open: boolean }) {
  const enabled = new Set(backends.map((b) => b.name));
  return (
    <details className={styles.help} open={open}>
      <summary className={styles.helpSummary}>Setting up a GPU</summary>
      <div className={styles.helpBody}>
        <p className={styles.note}>
          Each person does this once, on their own laptop. The sections named below are in SETUP.md at the repo's root.
        </p>
        {CHECKLISTS.map((list) => (
          <div key={list.name} className={styles.checklist}>
            <div className={styles.checklistHead}>
              <h3 className={styles.checklistTitle}>{list.title}</h3>
              {enabled.has(list.name) ? (
                <Badge tone="ok" label="Enabled" />
              ) : (
                <Badge tone="neutral" label="Not enabled here" />
              )}
            </div>
            <ol className={styles.checklistSteps}>
              {list.steps.map((step) => (
                <li key={step.text}>
                  {step.text} <span className={styles.cellSub}>SETUP.md, "{step.setup}"</span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </details>
  );
}
