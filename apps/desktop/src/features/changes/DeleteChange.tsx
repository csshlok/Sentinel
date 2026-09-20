import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useFormAction } from "@/components/FormDialog";
import { Button } from "@/components/ui/button";
import { deleteChange } from "@/services/actions";
import { changeKeys } from "@/services/changes";

/** Deleting removes the Change record from the runtime; the repository on disk is never touched. */
export function DeleteChange({ changeId, title }: { changeId: string; title: string }) {
  const [open, setOpen] = useState(false);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const del = useFormAction({
    run: () => deleteChange(changeId),
    invalidate: [],
    onSuccess: async () => {
      setOpen(false);
      // Drop the deleted Change's cached queries first so nothing refetches an id that no longer exists.
      qc.removeQueries({ queryKey: [...changeKeys.all, "detail", changeId] });
      await navigate({ to: "/changes" });
      await qc.invalidateQueries({ queryKey: changeKeys.all });
    },
  });
  return (
    <>
      <Button size="sm" variant="outline" className="text-danger" onClick={() => { del.reset(); setOpen(true); }}>Delete</Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={`Delete “${title}”?`}
        description="This removes the Change, its evidence and its event trace from the runtime. The repository itself is not touched. This can't be undone."
        confirmLabel="Delete Change"
        pending={del.isPending}
        error={del.error}
        onConfirm={() => del.mutate(undefined)}
      />
    </>
  );
}
