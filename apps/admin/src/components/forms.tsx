"use client";

import { type ReactNode, useActionState } from "react";
import { useFormStatus } from "react-dom";

import type { FormState } from "@/app/auth-actions";

import { Button } from "./ui";

export function SubmitButton({ children, pending, variant }: { children: ReactNode; pending?: string; variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const status = useFormStatus();
  return (
    <Button type="submit" disabled={status.pending} variant={variant}>
      {status.pending ? (pending ?? "Saving…") : children}
    </Button>
  );
}

/** Form bound to a server action returning {error?, ok?}; shows the result accessibly. */
export function ActionForm({
  action,
  children,
  className,
}: {
  action: (state: FormState, form: FormData) => Promise<FormState>;
  children: ReactNode;
  className?: string;
}) {
  const [state, formAction] = useActionState(action, undefined);
  return (
    <form action={formAction} className={className}>
      {children}
      {state?.error && (
        <p role="alert" className="mt-3 rounded-lg border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
          {state.error}
        </p>
      )}
      {state?.ok && (
        <p role="status" className="mt-3 rounded-lg border border-success/40 bg-success/10 px-3 py-2 text-sm text-success">
          {state.ok}
        </p>
      )}
    </form>
  );
}
