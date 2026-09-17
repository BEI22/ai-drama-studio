# Reference Image — v1

Version: `image_reference_v1`
Purpose: PRD Phase 5 — Character Reference / Location Reference

---

## System

国漫风格设定参考图，{style}

---

## User

{kind}设定：{name}
{detail}
{palette}
纯色简洁背景，正面视角，居中构图，完整可见，无动作，无文字，无其他人物

---

## Negative

低分辨率，模糊，文字，字幕，水印，签名，多个人物，复杂背景，剧烈动作，画面分割，多格漫画

---

## 说明（给维护者，不参与拼装）

参考图与分镜图的用途不同，提示词也就不同：分镜图要的是「这一格发生了什么」，
参考图要的是**可复用的视觉锚点** —— 所以这里固定要求正面、居中、纯色背景、
无动作，这样同一角色/Location 在后续几十个镜头里才有一个稳定的比对基准
（PRD §19 的 Reference Image 层）。

`{kind}` 取「角色」或「场景」；`{detail}` 是人物外貌三件套或场景描述与光线；
`{palette}` 只有场景会用到（`locations.visual_style`）。
