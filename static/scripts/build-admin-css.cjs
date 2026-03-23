const fs = require("fs");
const path = require("path");
const postcss = require("postcss");
const tailwind = require("@tailwindcss/postcss");
const autoprefixer = require("autoprefixer");

const inputPath = path.resolve(__dirname, "../assets/css/admin.tailwind.css");
const outputPath = path.resolve(__dirname, "../admin.css");

async function build() {
  const input = fs.readFileSync(inputPath, "utf8");
  const result = await postcss([
    tailwind(),
    autoprefixer(),
  ]).process(input, {
    from: inputPath,
    to: outputPath,
  });
  fs.writeFileSync(outputPath, result.css, "utf8");
}

build().catch((error) => {
  console.error(error);
  process.exit(1);
});
