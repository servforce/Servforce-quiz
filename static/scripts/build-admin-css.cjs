const fs = require("fs");
const path = require("path");
const postcss = require("postcss");
const tailwind = require("@tailwindcss/postcss");
const autoprefixer = require("autoprefixer");

const targets = [
  {
    inputPath: path.resolve(__dirname, "../assets/css/admin.tailwind.css"),
    outputPath: path.resolve(__dirname, "../admin.css"),
  },
  {
    inputPath: path.resolve(__dirname, "../assets/css/public.tailwind.css"),
    outputPath: path.resolve(__dirname, "../public.css"),
  },
];

async function buildTarget({ inputPath, outputPath }) {
  const input = fs.readFileSync(inputPath, "utf8");
  const result = await postcss([tailwind(), autoprefixer()]).process(input, {
    from: inputPath,
    to: outputPath,
  });
  fs.writeFileSync(outputPath, result.css, "utf8");
}

async function build() {
  for (const target of targets) {
    await buildTarget(target);
  }
}

build().catch((error) => {
  console.error(error);
  process.exit(1);
});
