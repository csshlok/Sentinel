import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { CircleCheck, FolderOpen, LoaderCircle } from "lucide-react";
import { useId, useRef, useState } from "react";
import { Notice } from "@/components/product";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { newIdempotencyKey } from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import type { RepositoryInfo } from "@/lib/api/types";
import { repoName, shortSha } from "@/lib/status";
import { changeKeys, createChange, validateRepository } from "@/services/changes";

type Check =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "ok"; info: RepositoryInfo }
  | { state: "error"; message: string };

const errorText = "text-xs text-danger";

export function NewChangeDialog({
  open,
  onOpenChange,
  returnFocusTo,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Element that opened the dialog; focus goes back to it on close. */
  returnFocusTo?: { current: HTMLElement | null };
}) {
  const uid = useId();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [title, setTitle] = useState("");
  const [intent, setIntent] = useState("");
  const [path, setPath] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [check, setCheck] = useState<Check>({ state: "idle" });
  // One key per unique request body; a retry of the same submission reuses it.
  const keyRef = useRef<{ signature: string; key: string } | null>(null);
  // Only the newest repository check may write its result; older, slower ones are ignored.
  const checkId = useRef(0);

  const reset = () => {
    setTitle("");
    setIntent("");
    setPath("");
    setSubmitted(false);
    setCheck({ state: "idle" });
    checkId.current += 1;
    create.reset();
    keyRef.current = null;
  };

  const create = useMutation({
    mutationFn: () => {
      const signature = JSON.stringify([title.trim(), intent.trim(), path.trim()]);
      if (keyRef.current?.signature !== signature) keyRef.current = { signature, key: newIdempotencyKey() };
      return createChange({ title: title.trim(), intent: intent.trim(), repository_path: path.trim() }, keyRef.current.key);
    },
    onSuccess: async (change) => {
      await queryClient.invalidateQueries({ queryKey: changeKeys.all });
      reset();
      onOpenChange(false);
      await navigate({ to: "/changes/$changeId", params: { changeId: change.id } });
    },
  });

  async function validate(candidate: string) {
    const value = candidate.trim();
    if (!value) return;
    const id = ++checkId.current;
    setCheck({ state: "checking" });
    try {
      const info = await validateRepository(value);
      if (id !== checkId.current) return;
      setCheck({ state: "ok", info });
      // Suggest a title from the repository name, but never overwrite what the user typed.
      setTitle((current) => current || `Changes in ${repoName(info.root)}`);
    } catch (error) {
      if (id !== checkId.current) return;
      setCheck({ state: "error", message: error instanceof ApiError ? error.message : "The repository could not be checked." });
    }
  }

  async function browse() {
    const result = await window.changeAssuranceDesktop?.repositories.selectFolder();
    if (result?.ok && result.path) {
      setPath(result.path);
      await validate(result.path);
    }
  }

  const missing = { title: !title.trim(), intent: !intent.trim(), path: !path.trim() };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (create.isPending) return;
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent
        className="sm:max-w-[520px]"
        onCloseAutoFocus={(event) => {
          if (returnFocusTo?.current) {
            event.preventDefault();
            returnFocusTo.current.focus();
          }
        }}
      >
        <form
          noValidate
          className="grid gap-5"
          onSubmit={(event) => {
            event.preventDefault();
            setSubmitted(true);
            if (create.isPending || missing.title || missing.intent || missing.path) return;
            create.mutate();
          }}
        >
          <DialogHeader>
            <DialogTitle>New Change</DialogTitle>
            <DialogDescription>
              Pick a repository and say what the work should achieve. The repository is only read; nothing in it is modified.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-1.5">
            <Label htmlFor={`${uid}-path`}>Repository</Label>
            <div className="flex gap-2">
              <Input
                id={`${uid}-path`}
                value={path}
                placeholder="C:\path\to\repository"
                onChange={(e) => {
                  setPath(e.target.value);
                  checkId.current += 1;
                  setCheck({ state: "idle" });
                }}
                onBlur={() => check.state === "idle" && void validate(path)}
                aria-invalid={(submitted && missing.path) || check.state === "error"}
                aria-describedby={`${uid}-path-status`}
                autoComplete="off"
                spellCheck={false}
                className="font-mono text-[13px]"
              />
              {window.changeAssuranceDesktop ? (
                <Button type="button" variant="outline" onClick={browse}>
                  <FolderOpen /> Browse
                </Button>
              ) : null}
            </div>
            <p id={`${uid}-path-status`} role="status" className="min-h-4 text-xs text-muted-foreground">
              {submitted && missing.path ? <span className={errorText}>Enter the repository path.</span> : null}
              {check.state === "checking" ? (
                <span className="inline-flex items-center gap-1.5">
                  <LoaderCircle className="size-3 animate-spin" aria-hidden="true" /> Checking repository…
                </span>
              ) : null}
              {check.state === "ok" ? (
                <span className="inline-flex items-center gap-1.5 text-ok">
                  <CircleCheck className="size-3.5" aria-hidden="true" />
                  <span className="text-muted-foreground">
                    Git repository · {check.info.branch ?? "detached HEAD"} @ <code>{shortSha(check.info.head_sha)}</code>
                  </span>
                </span>
              ) : null}
              {check.state === "error" ? <span className={errorText}>{check.message}</span> : null}
              {check.state === "idle" && !(submitted && missing.path) ? "The absolute path to a Git repository on this computer." : null}
            </p>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor={`${uid}-title`}>Title</Label>
            <Input
              id={`${uid}-title`}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              aria-invalid={submitted && missing.title}
              aria-describedby={submitted && missing.title ? `${uid}-title-err` : undefined}
              autoComplete="off"
            />
            {submitted && missing.title ? (
              <p id={`${uid}-title-err`} className={errorText}>
                Enter a short title for this Change.
              </p>
            ) : null}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor={`${uid}-intent`}>Intent</Label>
            <Textarea
              id={`${uid}-intent`}
              value={intent}
              onChange={(e) => setIntent(e.target.value)}
              aria-invalid={submitted && missing.intent}
              aria-describedby={`${uid}-intent-hint`}
              className="min-h-[84px]"
            />
            <p id={`${uid}-intent-hint`} className={submitted && missing.intent ? errorText : "text-xs text-muted-foreground"}>
              {submitted && missing.intent ? "Describe the intended outcome." : "What should this work achieve? Evidence is compared against this."}
            </p>
          </div>

          {create.isError ? (
            <Notice tone="danger" title="The Change wasn't created" role="alert">
              {create.error instanceof ApiError ? create.error.message : "The request failed."}
              {create.error instanceof ApiError && create.error.kind === "timeout"
                ? " It may have been created, so check the Changes list before trying again."
                : ""}
            </Notice>
          ) : null}

          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)} disabled={create.isPending}>
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Creating…" : "Create Change"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
