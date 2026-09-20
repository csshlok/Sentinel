import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Notice } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { newIdempotencyKey } from "@/lib/api";
import { ApiError, errorDetailLines } from "@/lib/api/client";
import { changeKeys } from "@/services/changes";
import { useReturnFocus } from "@/components/useReturnFocus";

export const errMessage = (e: unknown) => (e instanceof ApiError ? e.message : "The request failed.");

/** Native select styled like the inputs. Native keeps keyboard, screen-reader and Windows behavior for free. */
export function Select({ id, value, onChange, children, label, ...rest }: { id: string; value: string; onChange: (v: string) => void; children: ReactNode; label?: string } & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, "onChange" | "value" | "id">) {
  return (
    <select id={id} aria-label={label} value={value} onChange={(e) => onChange(e.target.value)} className="h-9 w-full rounded-md border border-input bg-card px-3 text-sm" {...rest}>
      {children}
    </select>
  );
}

export function Field({ id, label, hint, error, children }: { id: string; label: string; hint?: string; error?: string | null; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error || hint ? <p id={`${id}-h`} className={error ? "text-xs text-danger" : "text-xs text-muted-foreground"} role={error ? "alert" : undefined}>{error ?? hint}</p> : null}
    </div>
  );
}

/**
 * A modal form bound to one mutation. Owns the idempotency key for the submission (kept across retries of the *same* input, renewed when the
 * dialog reopens), the pending/error state, and refetching Change data afterwards. A pending request can't be dismissed.
 */
export function useFormAction<V, R>(opts: {
  run: (values: V, idempotencyKey: string) => Promise<R>;
  invalidate?: QueryKey[];
  onSuccess?: (result: R, values: V) => void;
}) {
  const qc = useQueryClient();
  const key = useRef(newIdempotencyKey());
  // React state (`isPending`) is stale within the same event tick, so a fast double click would otherwise start two submissions.
  const inFlight = useRef(false);
  const mutation = useMutation({
    mutationFn: (values: V) => opts.run(values, key.current),
    onSuccess: async (result, values) => {
      // Await the refetch so the screen behind the dialog is already current when it closes.
      await Promise.all((opts.invalidate ?? [changeKeys.all]).map((queryKey) => qc.invalidateQueries({ queryKey })));
      opts.onSuccess?.(result, values);
    },
    onSettled: () => { inFlight.current = false; },
  });
  const mutate = (values: V) => {
    if (inFlight.current) return;
    inFlight.current = true;
    mutation.mutate(values);
  };
  return { ...mutation, mutate, renewKey: () => { key.current = newIdempotencyKey(); } };
}

export function FormDialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  submit,
  pending,
  error,
  submitLabel,
  disabled,
  danger,
  width = "sm:max-w-[520px]",
  footerExtra,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: ReactNode;
  children: ReactNode;
  submit: () => void;
  pending: boolean;
  error: unknown;
  submitLabel: string;
  disabled?: boolean;
  danger?: boolean;
  width?: string;
  footerExtra?: ReactNode;
}) {
  const returnFocus = useReturnFocus(open);
  return (
    <Dialog open={open} onOpenChange={(o) => !pending && onOpenChange(o)}>
      <DialogContent className={width} {...returnFocus}>
        <form
          className="grid gap-4"
          noValidate
          onSubmit={(e) => {
            e.preventDefault();
            if (!pending && !disabled) submit();
          }}
        >
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          {children}
          {error ? (
            <Notice tone="danger" title="That didn't work" role="alert">
              {errMessage(error)}
              {errorDetailLines(error).map((l) => (
                <span key={l} className="mt-1 block">{l}</span>
              ))}
            </Notice>
          ) : null}
          <DialogFooter>
            {footerExtra}
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={pending}>Cancel</Button>
            <Button type="submit" variant={danger ? "destructive" : "default"} disabled={pending || disabled}>{pending ? "Working…" : submitLabel}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Dialog open state that resets its form when it opens; `reset` runs each time. */
export function useDialogState(reset: () => void) {
  const [open, setOpen] = useState(false);
  const resetRef = useRef(reset);
  useEffect(() => { resetRef.current = reset; });
  return { open, show: () => { resetRef.current(); setOpen(true); }, close: () => setOpen(false), onOpenChange: (o: boolean) => (o ? setOpen(true) : setOpen(false)) };
}
