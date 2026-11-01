// Verifies the production build is ONE self-contained script under the size budget.
import { readdirSync, readFileSync, statSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { createHash } from "node:crypto";

const files = readdirSync("dist").filter((f) => !f.startsWith("."));
if (files.length !== 1 || files[0] !== "trustdesk.js") {
  console.error(`expected exactly dist/trustdesk.js, found: ${files.join(", ")}`);
  process.exit(1);
}
const code = readFileSync("dist/trustdesk.js");
const gz = gzipSync(code).length;
const BUDGET_GZ = 90 * 1024;
console.log(`trustdesk.js: ${(statSync("dist/trustdesk.js").size / 1024).toFixed(1)} KB, ${(gz / 1024).toFixed(1)} KB gzip (budget ${BUDGET_GZ / 1024} KB)`);
if (/\bimport\(|from\s*["']https?:/.test(code.toString())) {
  console.error("bundle must not load other modules at runtime");
  process.exit(1);
}
if (gz > BUDGET_GZ) {
  console.error("bundle exceeds the gzip size budget");
  process.exit(1);
}
console.log(`integrity="sha384-${createHash("sha384").update(code).digest("base64")}" crossorigin="anonymous"`);
