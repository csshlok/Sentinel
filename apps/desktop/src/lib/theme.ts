export type ThemePreference = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

const KEY = "ca.theme.v1";
export const THEME_CHOICES: { value: ThemePreference; label: string }[] = [
  { value: "system", label: "Match my system" },
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
];

export const isThemePreference = (v: unknown): v is ThemePreference => v === "system" || v === "light" || v === "dark";
export const resolveTheme = (pref: ThemePreference, systemDark: boolean): ResolvedTheme => (pref === "system" ? (systemDark ? "dark" : "light") : pref);

export function readThemePreference(): ThemePreference {
  try {
    const v = localStorage.getItem(KEY);
    return isThemePreference(v) ? v : "system";
  } catch {
    return "system"; // storage can be blocked; the default still works
  }
}

const media = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null);

/** Applies the preference to <html>. `data-theme` drives the CSS tokens; `color-scheme` makes native controls and scrollbars follow. */
export function applyTheme(pref: ThemePreference = readThemePreference()): ResolvedTheme {
  const resolved = resolveTheme(pref, media()?.matches ?? false);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  return resolved;
}

export function setThemePreference(pref: ThemePreference): ResolvedTheme {
  try {
    localStorage.setItem(KEY, pref);
  } catch {
    /* applies for this session only */
  }
  return applyTheme(pref);
}

/** Re-applies when the OS theme changes while the preference is "system". Returns an unsubscribe function. */
export function watchSystemTheme(): () => void {
  const m = media();
  if (!m) return () => {};
  const listener = () => {
    if (readThemePreference() === "system") applyTheme("system");
  };
  m.addEventListener("change", listener);
  return () => m.removeEventListener("change", listener);
}
