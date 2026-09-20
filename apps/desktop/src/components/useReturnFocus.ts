import { useLayoutEffect, useRef } from "react";

/**
 * Returns focus to whatever had it before a dialog opened. Radix only does this for its own trigger, and these dialogs are opened by plain
 * buttons, so without this a keyboard user is dropped onto the page body after Escape. Spread the result onto `DialogContent`.
 * The opener is captured in a layout effect, which runs before Radix moves focus into the dialog.
 */
export function useReturnFocus(open: boolean) {
  const opener = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (open) opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }, [open]);
  return {
    onCloseAutoFocus: (event: Event) => {
      const target = opener.current;
      if (target && document.contains(target)) {
        event.preventDefault();
        target.focus();
      }
    },
  };
}
