# UI Workspace

`ui/` 是新前端源码目录，运行时构建产物输出到 `static/app/`。

## 命令

```bash
cd ui
npm install
npm run build
```

## 输出

- `static/app/index.html`
- `static/app/assets/app.css`
- `static/app/assets/app.js`
- `static/app/views/*.html`

运行时不依赖 Node；FastAPI 只读取 `static/app/` 下的构建结果。
