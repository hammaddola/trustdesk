// Copies the built widget into this app's public/ so it is served from the same port as the dashboard.
import { copyFileSync, existsSync } from "node:fs";

const src = new URL("../../widget/dist/trustdesk.js", import.meta.url);
if (!existsSync(src)) {
  console.error("Widget not built. Run: pnpm --filter @trustdesk/widget build");
  process.exit(1);
}
copyFileSync(src, new URL("../public/trustdesk.js", import.meta.url));
console.log("copied widget -> public/trustdesk.js");
