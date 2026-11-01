import { revalidatePath } from "next/cache";

import { PageHeader } from "@/components/ui";
import { type S, api, errorMessage } from "@/lib/api";

import { PlaygroundClient } from "./client";

export const metadata = { title: "Playground" };

export type PlaygroundResult = { ok: true; data: S["PlaygroundOut"] } | { ok: false; error: string };

async function ask(message: string, conversationId: string | null): Promise<PlaygroundResult> {
  "use server";
  const text = message.trim().slice(0, 2000);
  if (!text) return { ok: false, error: "Type a question first." };
  try {
    const data = await api<S["PlaygroundOut"]>("/v1/admin/playground", {
      method: "POST",
      body: JSON.stringify({ message: text, conversation_id: conversationId }),
    });
    revalidatePath("/conversations");
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: errorMessage(err) };
  }
}

export default function PlaygroundPage() {
  return (
    <>
      <PageHeader
        title="Playground"
        description="Internal testing tool. Ask questions exactly as a visitor would and see why the assistant answered or refused. Playground chats are excluded from visitor metrics."
      />
      <PlaygroundClient ask={ask} />
    </>
  );
}
