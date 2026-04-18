---
name: feishu-skill
description: 基于 lark-cli 的飞书多维表格写入工具。由用户手动触发，用于把本项目的角色/场景/分镜/视频产出同步到飞书 Base 在线多维表格。
trigger: 用户明确要求"同步到飞书表格"/"写飞书 Base"/"同步飞书"/"上传飞书多维表格"时使用
---

# 飞书 Skill（lark-cli 封装 · 手动触发）

> ✅ 仅在用户明确提出后使用，不纳入自动化主流程。
> 依赖：
> - 已全局安装 `@larksuite/cli`（命令 `lark-cli`）
> - 已完成 `lark-cli config init --new` + `lark-cli auth login --recommend`
> - 可用 `lark-cli auth status` 确认登录态
> - 官方配套 AI skills 已装到 `~/.agents/skills/`，详细 API 形参参考 `~/.agents/skills/lark-base/` 与 `~/.agents/skills/lark-shared/`

## 环境

- 全局命令：`lark-cli`（Node v20+ 已安装时可直接使用）
- 身份：`--as user`（默认 auto，未配 app token 时会用 user token）
- 输出：`--format json | table | csv | pretty`

## 适用场景（本项目）

把下列内容同步到飞书 Base：
1. **角色总表**：从 `projects/<项目名>/assets/characters.json` 批量写入（含变体关联）
2. **场景总表**：从 `scenes.json` 批量写入
3. **道具总表**：从 `props.json` 批量写入
4. **分镜总表**：从 `outputs/<episode>/06-shots/shot-NN.json` 批量写入（标题、类型、挂载、落幅、正文缩略）
5. **素材映射表**：从 `outputs/<episode>/asset-map.json` 批量写入（@图片N / @声音N → 真实文件路径）
6. **视频进度表**：从 `manifest.json → videos.shots` 批量写入（状态/时长/tail-frame 地址）

> 每次调用前必须确认 `app_token`（多维表格 appToken）与 `table_id` 由用户提供；找不到就停下来问用户。

## 核心命令速查

### 1. 登录态检查（每次开工前必做）

```bash
lark-cli auth status
# 输出 "logged in as ..." 表示就绪
```

### 2. 查看多维表格字段结构（建表/追列前必做）

```bash
# 列出所有字段
lark-cli api GET "/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields" --format table

# schema 查询（本地 CLI 内置）
lark-cli schema bitable.appTableField.list --format pretty
```

### 3. 批量新增记录（推荐，>1 条走 batch_create，省接口次数）

```bash
# records.json 结构：
# {
#   "records": [
#     {"fields": {"名称":"马上", "角色类型":"主持人", "描述":"博学沉稳..."}},
#     {"fields": {"名称":"马前卒", "角色类型":"主持人", "描述":"贱嘴浪马..."}}
#   ]
# }

lark-cli api POST \
  "/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/batch_create" \
  --data "@records.json" \
  --format pretty
```

### 4. 单条新增

```bash
lark-cli api POST \
  "/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records" \
  --data '{"fields": {"名称":"马上","描述":"博学沉稳"}}'
```

### 5. 查询记录（支持条件过滤）

```bash
# 拉全表（自动翻页）
lark-cli api GET \
  "/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records" \
  --page-all --format table

# 带过滤条件
lark-cli api GET \
  "/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records" \
  --params '{"filter":"CurrentValue.[名称]=\"马上\""}'
```

### 6. 更新记录

```bash
lark-cli api PUT \
  "/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records/{RECORD_ID}" \
  --data '{"fields":{"状态":"done"}}'
```

### 7. 新建字段（首次同步前建表用）

```bash
lark-cli api POST \
  "/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/fields" \
  --data '{"field_name":"名称","type":1}'
# type 速查：1=文本 2=数字 3=单选 4=多选 5=日期 7=复选框 11=人员 15=URL 17=附件 18=关联 19=公式 20=查找引用 21=评分 22=地理位置 1003=创建时间 1004=修改时间 1005=创建人 1006=修改人
```

## 常用同步流程（从项目 JSON → 飞书 Base）

### 场景 A · 同步角色总表（首次）

```bash
# 1. 由用户提供：APP_TOKEN / TABLE_ID（或 TABLE_NAME）
# 2. 用 jq 把 characters.json 转成 batch_create 需要的 payload
APP_TOKEN="bascn..."
TABLE_ID="tblxxx..."
CHAR_JSON="projects/马上看中国史/assets/characters.json"

jq '{records: [.[] | {fields: {
    "名称": .name,
    "角色类型": .role,
    "首次出现": .firstAppearInEpisode,
    "外观": .appearance,
    "服装": .clothing,
    "性格": .personality,
    "关联主角色": (.baseCharacter // ""),
    "变体类型": (.variantType // ""),
    "AI提示词": .aiPrompt
}}]}' "$CHAR_JSON" > /tmp/char-records.json

lark-cli api POST \
  "/open-apis/bitable/v1/apps/${APP_TOKEN}/tables/${TABLE_ID}/records/batch_create" \
  --data "@/tmp/char-records.json" \
  --format pretty
```

### 场景 B · 同步素材映射表

```bash
APP_TOKEN="bascn..."
TABLE_ID="tblxxx..."
MAP_JSON="projects/马上看中国史/outputs/ep01/asset-map.json"

jq '{records: [
  (.images | to_entries[] | {fields: {
    "引用编号": .key,
    "素材类型": .value.type,
    "名称": (.value.name // ("tail-shot-" + (.value.fromShot | tostring))),
    "文件路径": .value.file,
    "关联主角色": (.value.baseCharacter // ""),
    "集数": $ep
  }}),
  (.voices | to_entries[] | {fields: {
    "引用编号": .key,
    "素材类型": "voice",
    "名称": .value.name,
    "文件路径": .value.file,
    "集数": $ep
  }})
]}' --arg ep "ep01" "$MAP_JSON" > /tmp/assetmap-records.json

lark-cli api POST \
  "/open-apis/bitable/v1/apps/${APP_TOKEN}/tables/${TABLE_ID}/records/batch_create" \
  --data "@/tmp/assetmap-records.json" \
  --format pretty
```

### 场景 C · 同步分镜总表

```bash
APP_TOKEN="bascn..."
TABLE_ID="tblxxx..."
SHOTS_DIR="projects/马上看中国史/outputs/ep01/06-shots"

jq -s '{records: [.[] | {fields: {
  "分镜编号": (.index | tostring | ("#" + .)),
  "标题": .title,
  "类型": .shotType,
  "挂载": .mount,
  "起幅": .openingFrame,
  "落幅": .closingFrame,
  "过门": .transition,
  "正文": .mainPrompt,
  "MustShow": .mustShow,
  "集数": "ep01"
}}]}' "$SHOTS_DIR"/shot-*.json > /tmp/shots-records.json

lark-cli api POST \
  "/open-apis/bitable/v1/apps/${APP_TOKEN}/tables/${TABLE_ID}/records/batch_create" \
  --data "@/tmp/shots-records.json" \
  --format pretty
```

## 避坑要点

1. **APP_TOKEN/TABLE_ID 必须由用户提供**：本 skill 不猜、不默认、不从代码里读硬编码。找不到就停下来问。
2. **字段名必须与飞书表格里**已存在的列名**完全一致**（包括中文空格），否则会报 `FieldNameNotFound`。首次同步前先 `lark-cli api GET .../fields` 拉字段清单核对。
3. **批量上限 500 条/次**：超过请自己分页切片。
4. **速率**：默认每秒 20 请求；大批量 `batch_create` 可加 `--page-delay 300` 给缓冲。
5. **幂等**：batch_create 每次都会**新增**记录，不会去重；若要更新，先 GET 查到 record_id 再 PUT。
6. **错误码速查**：
   - `1254004` `FieldNameNotFound`：字段名写错
   - `1254005` `TableNotFound`：table_id 错误
   - `1254302` `AppNotFound`：app_token 错误或无权限
   - `99991664` `auth expired`：重新 `lark-cli auth login --recommend`
7. **敏感数据**：不要把 `--data` 里含密钥的原文写到可追溯日志里；必要时改用 `--data "@file.json"` 读文件。

## 触发方式

用户说出下列任一意图时启用：
- "同步到飞书表格/Base/多维表格"
- "写进飞书表"
- "上传飞书 Base"
- "同步 ep01 角色/场景/道具/分镜到飞书"
- "把素材映射表传到飞书"

**必须先确认**：
- `APP_TOKEN`（appToken，URL 里 `base/` 后面那段）
- `TABLE_ID`（tableId，URL 里 `&table=` 后面那段）或 `TABLE_NAME`
- 要同步的**数据源**（角色/场景/道具/分镜/映射表/视频进度 之一或多个）
- 是否需要**新建字段**（首次同步时往往需要）

三者缺一不可；缺就问用户。

## 关联参考

- 官方 skill 目录：`~/.agents/skills/lark-base/`（多维表格 API 详细签名）
- 本项目 asset-map 规范：`seedance2.0/.claude/skills/asset-map-skill/SKILL.md`
- 本项目分镜规范：`seedance2.0/.claude/skills/storyboard-writing-skill/prompt.md`
