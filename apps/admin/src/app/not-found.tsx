import Link from "next/link";

export default function NotFound() {
  return (
    <main className="flex min-h-[60vh] flex-col items-center justify-center gap-2 p-6 text-center">
      <h1 className="text-xl font-semibold">Not found</h1>
      <p className="text-sm text-muted">This item does not exist or belongs to another organization.</p>
      <Link href="/">Back to overview</Link>
    </main>
  );
}
