import { useState } from "react";
import { getTheme, toggleTheme } from "../theme";

/** Small button for the page header — flips the whole app between the
 * default dark theme and the light theme added specifically to make an
 * uploaded CAD drawing's linework easier to read on screen. See theme.ts. */
export function ThemeToggle() {
  const [theme, setThemeState] = useState(getTheme());

  return (
    <button
      type="button"
      className="btn btn-secondary"
      onClick={() => setThemeState(toggleTheme())}
      title={theme === "light" ? "Switch to dark mode" : "Switch to light mode"}
      style={{ fontSize: "0.78rem", padding: "0.5rem 0.75rem" }}
    >
      {theme === "light" ? "Dark mode" : "Light mode"}
    </button>
  );
}
