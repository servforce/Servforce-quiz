const fs = require("fs");
const path = require("path");

const projectRoot = path.resolve(__dirname, "..");
const runtimeTargets = [
  {
    source: path.join(projectRoot, "node_modules", "alpinejs", "dist", "cdn.min.js"),
    target: path.join(projectRoot, "assets", "js", "alpine.min.js"),
  },
];

for (const { source, target } of runtimeTargets) {
  if (!fs.existsSync(source)) {
    throw new Error(`缺少运行时资源: ${source}`);
  }
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
}
