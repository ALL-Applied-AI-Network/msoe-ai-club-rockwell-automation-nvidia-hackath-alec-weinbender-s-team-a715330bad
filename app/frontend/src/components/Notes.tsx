import { useState } from "react";
import { Banner } from "./Banner";
import { Button } from "./Button";
import styles from "./Notes.module.css";

const SHOWN = 2;

type NotesProps = {
  title: string; // e.g. "What these numbers assume"
  notes: string[]; // most important first: the first two always show
  tone?: "info" | "warn";
};

/** The caveats above a page's results, in one notice: the first two always show, the rest behind "Show all", so they
 *  don't push the results off the screen. */
export function Notes({ title, notes, tone = "info" }: NotesProps) {
  const [open, setOpen] = useState(false);
  if (notes.length === 0) return null;
  const shown = open ? notes : notes.slice(0, SHOWN);
  const more = notes.length - SHOWN;
  return (
    <Banner
      tone={tone}
      title={title}
      action={
        more > 0 && (
          <Button variant="ghost" size="sm" onClick={() => setOpen((o) => !o)}>
            {open ? "Show fewer" : `Show all ${notes.length}`}
          </Button>
        )
      }
    >
      <ul className={styles.list}>
        {shown.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </Banner>
  );
}
