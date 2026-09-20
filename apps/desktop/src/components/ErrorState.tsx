import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { ApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Notice } from "@/components/product";

/** Maps a normalized failure to honest, actionable copy. Auth, offline, and server faults look different. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const api = error instanceof ApiError ? error : null;
  const inBrowser = !window.changeAssuranceDesktop;

  let title = "Something went wrong";
  let body: ReactNode = api?.message ?? "The request failed unexpectedly.";
  let tone: "danger" | "warn" = "danger";

  switch (api?.kind) {
    case "auth":
      title = "Authentication required";
      tone = "warn";
      body = inBrowser ? (
        <>
          {api.message} Enter the development token in{" "}
          <Link to="/settings" className="underline underline-offset-2">
            Settings
          </Link>
          .
        </>
      ) : (
        <>
          {api.message} The desktop app could not authenticate with the local service. See{" "}
          <Link to="/settings" className="underline underline-offset-2">
            Settings
          </Link>
          .
        </>
      );
      break;
    case "offline":
      title = "Can't reach the local service";
      body = "Nothing answered on the local API address. Start the backend, then try again.";
      break;
    case "timeout":
      title = "The service is taking too long";
      body = "If you were changing something, it may have gone through. Refresh before trying again.";
      break;
    case "not_found":
      title = "Not found";
      break;
    case "conflict":
      title = "Conflict";
      break;
    case "validation":
      title = "The request was rejected";
      break;
    case "server":
      title = "The service reported an error";
      break;
  }

  return (
    <Notice
      tone={tone}
      title={title}
      role="alert"
      action={
        onRetry ? (
          <Button variant="outline" size="sm" onClick={onRetry}>
            Try again
          </Button>
        ) : undefined
      }
    >
      {body}
    </Notice>
  );
}
