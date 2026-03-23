#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");
const postcss = require("postcss");
const tailwind = require("@tailwindcss/postcss");
const autoprefixer = require("autoprefixer");

const root = path.resolve(__dirname, "..");
const projectRoot = path.resolve(root, "..");
const outDir = path.join(projectRoot, "static", "app");
const assetDir = path.join(outDir, "assets");
const viewSrc = path.join(root, "src", "views");
const viewOut = path.join(outDir, "views");

function ensureDir(target) {
  fs.mkdirSync(target, { recursive: true });
}

async function buildCss() {
  const inputPath = path.join(root, "src", "styles", "app.css");
  const outputPath = path.join(assetDir, "app.css");
  const source = fs.readFileSync(inputPath, "utf8");
  const result = await postcss([tailwind(), autoprefixer]).process(source, {
    from: inputPath,
    to: outputPath,
  });
  fs.writeFileSync(outputPath, result.css, "utf8");
}

function copyFile(source, target) {
  ensureDir(path.dirname(target));
  fs.copyFileSync(source, target);
}

function copyTree(source, target) {
  ensureDir(target);
  for (const entry of fs.readdirSync(source, { withFileTypes: true })) {
    const src = path.join(source, entry.name);
    const out = path.join(target, entry.name);
    if (entry.isDirectory()) {
      copyTree(src, out);
      continue;
    }
    copyFile(src, out);
  }
}

async function main() {
  ensureDir(outDir);
  ensureDir(assetDir);
  ensureDir(viewOut);

  await buildCss();
  copyFile(path.join(root, "templates", "index.html"), path.join(outDir, "index.html"));
  copyFile(path.join(root, "src", "app", "main.js"), path.join(assetDir, "app.js"));
  copyTree(viewSrc, viewOut);
  console.log(`[ui] built -> ${outDir}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
