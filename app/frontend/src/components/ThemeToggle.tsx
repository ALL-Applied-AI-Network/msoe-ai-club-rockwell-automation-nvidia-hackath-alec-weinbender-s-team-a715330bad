import { setTheme, useTheme } from "../theme";
import styles from "./ThemeToggle.module.css";

/** Light or dark, in the top bar. */
export function ThemeToggle() {
  const theme = useTheme();
  return (
    <div className={styles.toggle} role="group" aria-label="Color mode">
      {(["light", "dark"] as const).map((option) => (
        <button
          key={option}
          type="button"
          className={styles.option}
          aria-pressed={theme === option}
          onClick={() => setTheme(option)}
        >
          {option === "light" ? "Light" : "Dark"}
        </button>
      ))}
    </div>
  );
}
