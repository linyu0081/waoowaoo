---
name: asset-map-skill
description: 扫描集级资产目录（images/audio/tail-frames），生成 asset-map.json，建立 @图片N/@声音N 全局编号
tools: read, write, ls
---

# Asset Map Skill · 集级素材映射表生成器

## 用途

在分镜师生产前，扫描指定项目+集数的资产目录，产出 `asset-map.json`。下游 `storyboard-writing-skill` 的 mount 字段将严格引用本表编号，确保"@图片N/@声音N"在全集内唯一稳定、跨镜一致。

## 输入

```json
{
  "projectName": "<项目名>",
  "episode": "ep01",
  "assetsDir": "projects/<项目名>/assets/",
  "tailFrameDir": "projects/<项目名>/outputs/<episode>/tail-frames/",
  "totalShots": 9,
  "characters": [...],
  "scenes": [...],
  "props": [...]
}
```

其中 `characters / scenes / props` 直接复用 `assets/characters.json / scenes.json / props.json` 的数组。

## 编号规则（严格按此顺序，不得更改）

### images（全集唯一）
从 `@图片1` 开始顺序递增，按下列顺序入表：

1. **角色正身**（按 characters.json 顺序，跳过 variant：`baseCharacter` 字段存在的条目留到第 2 步）
2. **角色变体**：紧随其主角色之后插入（按 characters.json 中出现顺序）。一个主角色下多个变体时，按出现顺序连续编号。
3. **场景**（按 scenes.json 顺序）
4. **道具**（按 props.json 顺序）
5. **尾帧**：末尾预占 `totalShots` 个编号，对应 tail-shot-00 ~ tail-shot-{N-1}

文件字段统一写相对路径（相对项目根 `projects/<项目名>/`）：
- 角色/变体：`assets/images/char-<name>.png`
- 场景：`assets/images/scene-<name>.png`
- 道具：`assets/images/prop-<name>.png`
- 尾帧：`outputs/<episode>/tail-frames/tail-shot-{index:02d}.jpg`

### voices（全集唯一）
从 `@声音1` 开始，扫描 `assets/audio/voice-*.mp3|wav|m4a|ogg`，按文件名字典序入表。
文件字段：`assets/audio/voice-<name>.<ext>`

## 输出 JSON schema

```json
{
  "episode": "ep01",
  "generatedAt": "<ISO>",
  "images": {
    "@图片1": { "type": "character", "name": "马上", "file": "assets/images/char-马上.png" },
    "@图片5": { "type": "character-variant", "name": "赵匡胤·黄袍加身", "baseCharacter": "赵匡胤", "file": "..." },
    "@图片19": { "type": "scene", "name": "演播室", "timeOfDay": "日", "file": "..." },
    "@图片31": { "type": "prop", "name": "黄色纛旗", "file": "..." },
    "@图片39": { "type": "tail-frame", "fromShot": 0, "file": "outputs/ep01/tail-frames/tail-shot-00.jpg" }
  },
  "voices": {
    "@声音1": { "name": "马上", "file": "assets/audio/voice-马上.mp3" }
  }
}
```

key 名、字段名严格固定。`tail-frame` 条目即使文件尚不存在也必须预占编号（生视频流水线将按此 path 落盘截帧）。

## 输出路径

`projects/<项目名>/outputs/<episode>/asset-map.json`

## 铁律

1. **全集内编号唯一稳定**：一旦生成，后续分镜生产不得改动任何编号。
2. **变体紧随主角色**：`baseCharacter` 非空的条目，其编号必须紧跟 `baseCharacter` 的编号之后。
3. **尾帧预占**：`totalShots` 个尾帧占位必须在本表生成时一次性分配完毕，后续无需追加。
4. **只扫资产目录不写正文**：本 skill 不生成任何自然语言内容，仅做文件映射。
5. **幂等**：同样输入必产出同样 JSON（编号顺序完全由输入 json 顺序决定）。

## 调用方

- `storyboard-artist`：在大纲确认后、调用 `storyboard-writing-skill` 之前调用本 skill。
- `ai-producer`：生视频流水线启动时加载本表以解析 `@图片N/@声音N` 到真实文件。
