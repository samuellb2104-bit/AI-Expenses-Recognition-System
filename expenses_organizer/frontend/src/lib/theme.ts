import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "costoad-theme";
const listeners = new Set<() => void>();
const media = window.matchMedia("(prefers-color-scheme: dark)");

function storedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null;
  }
}

/** Explicit choice if the user made one, otherwise the operating-system theme. */
function resolveTheme(): Theme {
  return storedTheme() ?? (media.matches ? "dark" : "light");
}

function apply() {
  document.documentElement.dataset.theme = resolveTheme();
}

function emit() {
  listeners.forEach((listener) => listener());
}

// Follow the OS theme live, but only while the user has not picked one.
media.addEventListener("change", () => {
  if (storedTheme() === null) {
    apply();
    emit();
  }
});

apply();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function toggleTheme() {
  const next: Theme = resolveTheme() === "dark" ? "light" : "dark";
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* private mode: the choice just lasts until reload */
  }
  document.documentElement.dataset.theme = next;
  emit();
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, resolveTheme);
  return { theme, toggle: toggleTheme };
}
