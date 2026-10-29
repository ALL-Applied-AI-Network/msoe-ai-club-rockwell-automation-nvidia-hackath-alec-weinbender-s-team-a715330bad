import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const KEY = "auto-grasp-theme";
const listeners = new Set<() => void>();

function saved(): Theme | null {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage blocked: fall back to the system setting
  }
}

let current: Theme = saved() ?? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
document.documentElement.dataset.theme = current;

/** Switch the theme and remember it. Charts and other pages follow through useTheme. */
export function setTheme(theme: Theme) {
  current = theme;
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    // not remembered; the choice still holds until the page closes
  }
  listeners.forEach((listener) => listener());
}

/** The theme in use. The first visit follows the system's light or dark setting. */
export function useTheme(): Theme {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => current,
  );
}
