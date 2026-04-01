import { build, context } from "esbuild";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, "..");
const srcDir = path.join(root, "src");
const distDir = path.join(root, "dist");
const watch = process.argv.includes("--watch");
const cleanOnly = process.argv.includes("--clean");

async function ensureDir(dir) {
  await fs.mkdir(dir, { recursive: true });
}

async function writeFile(filePath, content) {
  await ensureDir(path.dirname(filePath));
  await fs.writeFile(filePath, content, "utf8");
}

async function copyFile(from, to) {
  await ensureDir(path.dirname(to));
  await fs.copyFile(from, to);
}

async function clean() {
  await fs.rm(distDir, { recursive: true, force: true });
}

async function emitHtml() {
  const backgroundHtml = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Overwolf Game Bridge Background</title>
  </head>
  <body>
    <script src="./index.js"></script>
  </body>
</html>
`;

  const desktopHtml = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Overwolf Game Bridge</title>
    <link rel="stylesheet" href="./index.css" />
  </head>
  <body>
    <main>
      <h1>Overwolf Game Bridge</h1>
      <p id="status">Bridge UI scaffold ready.</p>
    </main>
    <script src="./index.js"></script>
  </body>
</html>
`;

  await writeFile(path.join(distDir, "background", "index.html"), backgroundHtml);
  await writeFile(path.join(distDir, "desktop", "index.html"), desktopHtml);
  await copyFile(path.join(srcDir, "desktop", "index.css"), path.join(distDir, "desktop", "index.css"));
}

const sharedBuildOptions = {
  bundle: true,
  platform: "browser",
  target: ["es2020"],
  format: "iife",
  sourcemap: true,
  logLevel: "info",
};

async function buildOnce() {
  await clean();
  await ensureDir(distDir);
  await Promise.all([
    build({
      ...sharedBuildOptions,
      entryPoints: [path.join(srcDir, "background", "index.ts")],
      outfile: path.join(distDir, "background", "index.js"),
    }),
    build({
      ...sharedBuildOptions,
      entryPoints: [path.join(srcDir, "desktop", "index.ts")],
      outfile: path.join(distDir, "desktop", "index.js"),
    }),
  ]);
  await emitHtml();
  console.log("Built Overwolf app scaffold into dist/");
}

async function watchBuild() {
  await clean();
  await ensureDir(distDir);
  const bgCtx = await context({
    ...sharedBuildOptions,
    entryPoints: [path.join(srcDir, "background", "index.ts")],
    outfile: path.join(distDir, "background", "index.js"),
  });
  const desktopCtx = await context({
    ...sharedBuildOptions,
    entryPoints: [path.join(srcDir, "desktop", "index.ts")],
    outfile: path.join(distDir, "desktop", "index.js"),
  });
  await bgCtx.watch();
  await desktopCtx.watch();
  await emitHtml();
  console.log("Watching Overwolf app scaffold...");
}

if (cleanOnly) {
  await clean();
  console.log("Cleaned dist/");
} else if (watch) {
  await watchBuild();
} else {
  await buildOnce();
}
