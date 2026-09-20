import { useEffect, useState } from "react";
import type { DesktopWindowState } from "@/types/desktop";

const INITIAL: DesktopWindowState = { maximized: false, fullScreen: false };

/**
 * Frameless-window controls. There is no permanent title bar: a thin hover zone at the top edge reveals
 * a drag bar with minimize / maximize / close (see `.window-chrome` in app.css). Renders nothing in a browser.
 */
export function WindowChrome() {
  const controls = window.changeAssuranceDesktop?.windowControls;
  const [state, setState] = useState(INITIAL);

  useEffect(() => {
    if (!controls) return;
    let active = true;
    void controls.getState().then((next) => active && setState(next));
    const unsubscribe = controls.onStateChanged((next) => active && setState(next));
    return () => {
      active = false;
      unsubscribe();
    };
  }, [controls]);

  if (!controls) return null;
  const expanded = state.maximized || state.fullScreen;

  return (
    <div className="window-chrome-layer">
      <div className="window-reveal-zone" aria-hidden="true" />
      <header className="window-chrome">
        <div className="window-controls" role="group" aria-label="Window controls">
          <button type="button" className="window-control" aria-label="Minimize" title="Minimize" onClick={() => void controls.minimize()}>
            <span className="window-icon window-icon-minimize" aria-hidden="true" />
          </button>
          <button
            type="button"
            className="window-control"
            aria-label={expanded ? "Restore" : "Maximize"}
            title={expanded ? "Restore" : "Maximize"}
            onClick={() => void controls.toggleMaximize().then(setState)}
          >
            <span className={`window-icon ${expanded ? "window-icon-restore" : "window-icon-maximize"}`} aria-hidden="true" />
          </button>
          <button type="button" className="window-control window-control-close" aria-label="Close" title="Close" onClick={() => void controls.close()}>
            <span className="window-icon window-icon-close" aria-hidden="true" />
          </button>
        </div>
      </header>
    </div>
  );
}
