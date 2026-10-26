import { useEffect, useRef } from "react";
import { Icon } from "./Icon";
import styles from "./SearchInput.module.css";

type SearchInputProps = {
  value: string;
  onChange: (value: string) => void;
  placeholder: string; // what can be searched, e.g. "Search by part number, name or ID"
  label?: string; // for screen readers; the placeholder by default
};

/** A list's search box. Ctrl+K (Cmd+K on a Mac) focuses it from anywhere on the page. */
export function SearchInput({ value, onChange, placeholder, label }: SearchInputProps) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const focus = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        input.current?.focus();
      }
    };
    document.addEventListener("keydown", focus);
    return () => document.removeEventListener("keydown", focus);
  }, []);

  return (
    <label className={styles.box}>
      <Icon name="search" />
      <input
        ref={input}
        type="search"
        className={styles.input}
        value={value}
        placeholder={placeholder}
        aria-label={label ?? placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
      <kbd className={styles.key}>Ctrl K</kbd>
    </label>
  );
}
