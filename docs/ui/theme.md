# UI 主题覆盖

本文件是项目内 UI 配色与视觉语义的事实来源，供 [static-ui skill](../../skills/static-ui/SKILL.md) 优先读取。

- 适用范围：`templates/`、`static/`、管理后台、候选人端页面。
- 目标风格：深色优先、现代克制、偏管理后台；主色调统一为“蓝色 + 绿色”。
- 约束：后续涉及主题色、强调色、渐变方向、状态色取舍时，以本文件为准；`skills/static-ui/SKILL.md` 中的默认配色仅作为兜底，不再视为本项目事实来源。

## 主题原则

- 主品牌观感：冷黑底上的蓝色到绿色渐变，清晰、专业、偏系统控制台气质。
- 中性色职责：负责背景、分层、边框、正文可读性，不抢品牌色。
- 品牌色职责：只用于主按钮、激活态、焦点态、关键图标、关键数据高亮。
- 危险/警告/信息色仍保持语义独立，不要把所有状态都染成品牌蓝绿。

## 配色语义槽位

### Base

- 页面背景：`bg-slate-950`
- 二级背景：`bg-slate-900`
- 面板背景：`bg-slate-900/55`
- 更弱面板底：`bg-slate-950/35`
- 顶栏背景：`bg-slate-950/72`
- 边框/分割线：`border-slate-800`、`divide-slate-800`
- Hover：`hover:bg-slate-900/70`
- 主文字：`text-slate-100`
- 次文字：`text-slate-300`
- 弱化文字：`text-slate-400`
- 占位文字：`placeholder-slate-500`

推荐 CSS 变量：

```css
:root {
  --ui-bg: #020617;
  --ui-bg-soft: #0f172a;
  --ui-panel: rgba(15, 23, 42, 0.55);
  --ui-panel-soft: rgba(2, 6, 23, 0.35);
  --ui-border: rgba(51, 65, 85, 0.9);
  --ui-text: #f8fafc;
  --ui-text-muted: #cbd5e1;
  --ui-text-soft: #94a3b8;
}
```

### Primary

- 主色 1（蓝色）：`#2563eb`
- 主色 2（青蓝）：`#0ea5e9`
- 主色 3（绿色）：`#22c55e`
- 品牌渐变：仅用于背景氛围、插画、轻量高亮，不默认用于按钮
- 实心按钮：`bg-blue-600 text-white hover:bg-blue-700`
- 品牌弱底：`bg-blue-500/12 text-blue-700 border-blue-500/28`
- 激活高亮：`bg-gradient-to-r from-blue-500/18 to-green-500/18 text-blue-800 border-blue-500/24`
- Focus ring：`focus:ring-2 focus:ring-blue-500/32 focus:border-blue-500/36`
- 品牌状态点：`bg-blue-500`

推荐 CSS 变量：

```css
:root {
  --ui-primary: #2563eb;
  --ui-primary-strong: #1d4ed8;
  --ui-secondary: #22c55e;
  --ui-secondary-strong: #16a34a;
  --ui-brand-gradient: linear-gradient(135deg, #2563eb 0%, #0ea5e9 45%, #22c55e 100%);
}
```

### Danger

- 危险弱底：`bg-rose-500/18 text-rose-200 border-rose-500/24`
- 危险文案：`text-rose-300`
- 危险状态点：`bg-rose-400`

### Warning

- 警告弱底：`bg-amber-500/16 text-amber-200 border-amber-500/24`
- 警告文案：`text-amber-300`

### Info

- 信息弱底：`bg-sky-500/16 text-sky-200 border-sky-500/24`
- 信息文案：`text-sky-300`

### Overlay

- 遮罩：`bg-slate-950/78`
- 带品牌氛围的遮罩可叠加：
  `background: radial-gradient(circle at top left, rgba(37, 99, 235, 0.14), transparent 32%), radial-gradient(circle at top right, rgba(34, 197, 94, 0.16), transparent 36%), rgba(2, 6, 23, 0.78);`

## 组件使用规则

- 主按钮默认使用单色实心，不使用渐变填充；主操作优先蓝色，明确成功语义时再用绿色。
- 激活 tab、选中菜单、当前页签优先用“蓝色到绿色”的弱渐变底，不要只换文字颜色。
- 大面积背景不要直接铺满高饱和蓝色或绿色；品牌色应集中在交互点、标题点缀、图标、数据强调。
- 卡片/面板仍以中性色为主，品牌色只出现在边框发光、顶部细线、状态块、按钮。
- 输入框 focus 态优先用 `blue` ring；错误校验仍用 `rose`，不要混用品牌色和错误色。

## 图标与插画建议

- Logo、主视觉图标、关键空状态插画优先使用“蓝色 + 绿色”渐变描边或渐变填充。
- 若图标需要浅色内芯，优先白色或 `slate-50`，外圈保持透明或深底，不要再叠额外白色卡片底。

## 禁止项

- 禁止把主按钮继续做成绿色系，除非该按钮表达“成功/通过/完成”。
- 禁止同时混用多组主色，例如页面里再引入蓝绿渐变作为另一套品牌色。
- 禁止在正文大段文字、表格全文、输入正文里使用高饱和蓝色/绿色。

## 落地优先级

1. 品牌元素：logo、顶部品牌区、主按钮、激活菜单。
2. 交互反馈：focus ring、选中态、标签态、关键空状态。
3. 氛围层：背景光晕、局部渐变分隔、插画色系。

## 给 `static-ui` skill 的执行说明

- 当页面未指定颜色时，默认采用本文件的 `Base + Primary + Overlay` 组合。
- 当 `skills/static-ui/SKILL.md` 与本文件冲突时，以本文件为准。
- 新页面应优先复用本文件语义槽位，不要在模板或样式里散落硬编码颜色。
