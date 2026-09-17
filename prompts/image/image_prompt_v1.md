# Image Prompt Builder — v1

Version: `image_prompt_v1`
Layers: PRD §19 — System Style + Character Description + Location Description + Current Shot + Camera + Emotion + Reference Image

---

## System

国漫风格漫剧单帧分镜，{style}

---

## User

{framing}，{core}
{characters}
{location}
{lighting}
运镜：{camera}
{emotion}
{reference}

---

## Negative

低分辨率，模糊，畸形或多出的手指，文字，字幕，水印，签名，画面分割，多格漫画，重复人物

---

## 说明（给维护者，不参与拼装）

这不是发给 LLM 的提示词。文生图模型没有对话能力，所以 PRD §19 的六层约束
必须在**调用前**拼装成一段文本 —— 这个文件就是那段文本的模板，所有措辞都在这里，
Python 只负责把领域对象映射成上面这些变量（见 `app/services/prompt_builder.py`）。

各层来源：

| 占位符 | PRD §19 对应层 | 来源 |
| --- | --- | --- |
| `{style}` | System Style | `projects.style` + Story Bible `style` |
| `{characters}` | Character Description | `characters.appearance` / `hair` / `clothing` |
| `{location}` | Location Description | `locations.description` |
| `{lighting}` | Location Description | `locations.lighting` |
| `{framing}` | Current Shot | `shots.shot_size` |
| `{core}` | Current Shot | `shots.visual_description` / `action` |
| `{camera}` | Camera | `shots.camera_movement` |
| `{emotion}` | Emotion | `shots.expression` |
| `{reference}` | Reference Image | `characters.reference_image_url` / `locations.reference_image_url` |

拼装规则：**某个占位符为空时，其所在行整行丢弃**（见 builder 的 `_assemble`）。
否则空层会在提示词里留下「人物：」这样的半句话，反而干扰模型。
