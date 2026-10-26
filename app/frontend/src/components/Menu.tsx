import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { Icon } from "./Icon";
import styles from "./Menu.module.css";

export type MenuItem = {
  label: string;
  to?: string; // a page to open
  onSelect?: () => void; // or an action to run
  disabled?: boolean;
  title?: string; // why it's disabled, or what it does
  danger?: boolean; // stops or throws away work
};

/** A row's other actions behind a "more" button: what doesn't fit as a button of its own. Closes on a choice, a click
 *  outside or Escape. */
export function Menu({ label, items }: { label: string; items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const outside = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const shown = items.filter(Boolean);
  if (shown.length === 0) return null;
  return (
    <div className={styles.box} ref={box}>
      <button type="button" className={styles.trigger} aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="more" />
      </button>
      {open && (
        <div className={styles.menu} role="menu">
          {shown.map((item) =>
            item.to && !item.disabled ? (
              <Link key={item.label} to={item.to} role="menuitem" className={styles.item} title={item.title} onClick={() => setOpen(false)}>
                {item.label}
              </Link>
            ) : (
              <button
                key={item.label}
                type="button"
                role="menuitem"
                className={`${styles.item} ${item.danger ? styles.danger : ""}`}
                disabled={item.disabled}
                title={item.title}
                onClick={() => {
                  setOpen(false);
                  item.onSelect?.();
                }}
              >
                {item.label}
              </button>
            ),
          )}
        </div>
      )}
    </div>
  );
}
