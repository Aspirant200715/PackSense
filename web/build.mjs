import { cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const root = new URL("./", import.meta.url);
const output = new URL("./dist/", root);
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
for (const name of ["index.html", "styles.css"]) {
  await cp(new URL(name, root), new URL(name, output));
}
await cp(new URL("src/", root), new URL("src/", output), { recursive: true });
console.log(`Built ${fileURLToPath(output)}`);
