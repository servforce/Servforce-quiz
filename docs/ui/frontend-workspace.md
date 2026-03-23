# 前端工作区说明

## 目录

```text
ui/
  package.json
  scripts/build-ui.cjs
  templates/index.html
  src/
    app/main.js
    styles/app.css
    views/*.html
```

## 构建

```bash
scripts/dev/build-ui.sh
```

输出到：

- `static/app/index.html`
- `static/app/assets/app.css`
- `static/app/assets/app.js`
- `static/app/views/*.html`

## 设计原则

- 保留当前蓝绿基础配色
- 不沿用 `raelyn` 的深色主题
- 构建阶段允许 Node
- 运行阶段只读取 `static/app/`
- 页面由 FastAPI 静态输出，不依赖服务端 Jinja 渲染业务状态
