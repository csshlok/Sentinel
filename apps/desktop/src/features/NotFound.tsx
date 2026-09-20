import { Link } from "@tanstack/react-router";
import { EmptyState } from "@/components/product";
import { Button } from "@/components/ui/button";

export function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      action={
        <Button asChild variant="outline">
          <Link to="/changes">Back to Changes</Link>
        </Button>
      }
    >
      That address doesn't match a screen in this app.
    </EmptyState>
  );
}
