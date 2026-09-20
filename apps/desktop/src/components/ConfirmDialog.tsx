import type { ReactNode } from "react";
import { Notice } from "@/components/product";
import { errMessage } from "@/components/FormDialog";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { errorDetailLines } from "@/lib/api/client";
import { useReturnFocus } from "@/components/useReturnFocus";

/** A confirmation that names its target and consequence. Pending work can't be dismissed; errors stay visible for another try. */
export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, pending, error, onConfirm, danger = true, children }: {
  children?: ReactNode;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  pending: boolean;
  error?: unknown;
  onConfirm: () => void;
  danger?: boolean;
}) {
  const returnFocus = useReturnFocus(open);
  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className="sm:max-w-[440px]" {...returnFocus}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        {children}
        {error ? (
          <Notice tone="danger" title="That didn't work" role="alert">
            {errMessage(error)}
            {errorDetailLines(error).map((l) => <span key={l} className="mt-1 block">{l}</span>)}
          </Notice>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button>
          <Button type="button" variant={danger ? "destructive" : "default"} onClick={onConfirm} disabled={pending}>{pending ? "Working…" : confirmLabel}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
