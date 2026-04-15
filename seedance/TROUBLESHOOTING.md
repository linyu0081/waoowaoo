# Seedance Studio — 问题排查与解决方案

> 本文档记录了 `viewer.html` 页面开发过程中遇到的所有问题及解决方案。

---

## 目录

1. [页面加载极慢（20~25 个无效 HEAD 请求）](#1-页面加载极慢)
2. [修改代码后页面不更新（HTTP 缓存问题）](#2-修改代码后页面不更新)
3. [角色/场景图片不显示（路径拼接错误）](#3-角色场景图片不显示)
4. [场景图 fallback 逻辑 bug（onerror 全部执行）](#4-场景图-fallback-逻辑-bug)
5. [剧本内容不显示（JSON 格式不兼容）](#5-剧本内容不显示)
6. [本地 Mac 无法访问远程服务器页面](#6-本地-mac-无法访问远程服务器页面)
7. [SSH 端口转发失败（端口号错误）](#7-ssh-端口转发失败)

---

## 1. 页面加载极慢

### 现象
每次切换项目或刷新页面，需要等待 5~10 秒才能加载完成。

### 根因
`loadProject()` 函数中有暴力探测逻辑，每次发出 **20~25 个 HTTP HEAD 请求**（探测 `ep01`~`ep20` 的 `manifest.json` 和 `01-clips.json`），大部分返回 404，每个都有网络开销。

```javascript
// ❌ 旧代码：暴力探测 20 个集数
for (let i = 1; i <= 20; i++) {
  const epKey = `ep${String(i).padStart(2, '0')}`;
  probeEpisodes.push(epKey);
}
await Promise.all(probeEpisodes.map(async (ep) => {
  const res = await fetch(`.../${ep}/manifest.json`, { method: 'HEAD' });
}));
```

### 解决方案
直接从 `.agent-state.json` 读取已知集数，**0 个额外请求**：

```javascript
// ✅ 新代码：直接从 agentState 读取
const stateEpisodes = Object.keys(projectState?.episodes || {});
const allEpisodes = stateEpisodes.length > 0 ? stateEpisodes.sort() : ['ep01'];
```

---

## 2. 修改代码后页面不更新

### 现象
修改了 `viewer.html` 后刷新页面，内容毫无变化。清空缓存+强制刷新也无效。有时等半小时后自己好了。

### 根因
**三层缓存叠加**：

1. **Python `http.server` 无 `Cache-Control` 头**：默认只发 `Last-Modified`，浏览器做启发式缓存
2. **VS Code 端口转发缓存**：VS Code Remote 的端口转发通过 WebSocket 隧道代理，有自己的缓存层
3. **浏览器磁盘缓存**：HTML 中的 `<meta http-equiv="Cache-Control">` 对浏览器几乎无效（HTTP 响应头优先级更高）

### 解决方案

**创建了 `serve.py` 替代原生 `http.server`**，所有响应都带无缓存头：

```python
class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()
```

**启动方式**：
```bash
cd seedance && python3 serve.py 8899
```

**额外措施**：
- `loadJSON()` 中所有 fetch URL 追加 `?_t=时间戳` 参数
- `buildImgWithFallback()` 中所有图片 URL 也追加时间戳
- `loadJSON()` 加了 5 秒超时（`AbortController`），避免请求不存在的文件时长时间挂起

---

## 3. 角色/场景图片不显示

### 现象
资产库中角色和场景的图片全部不显示（图片区域空白）。

### 根因

**角色图片**：代码 fallback 路径是 `char-{name}.png`，但实际文件名是 `char-{name}-base.png`（如 `char-叶烬-base.png`）。

**场景图片**：
- 代码使用 `scene-` 前缀，但实际文件名是 `loc-` 前缀
- `locations.json` 中场景名带时间后缀（如 `曙光城中央广场_黄昏`），但图片文件名不带（`loc-曙光城中央广场.png`）

### 解决方案

新增 `buildImgWithFallback()` 函数，为每张图片构建多个候选路径，通过 `onerror` 依次尝试：

- **角色**：`refImage` → `char-{name}-base.png` → `char-{name}.png`
- **场景**：`refImage` → `loc-{name}.png` → `loc-{去掉时间后缀}.png` → `scene-{name}.png`

---

## 4. 场景图 fallback 逻辑 bug

### 现象
即使 fallback 路径列表中包含正确的图片路径，图片仍然不显示。

### 根因
`buildImgWithFallback` 的 `onerror` 中，多个 fallback 语句用 `;` 连接，**全部会执行**，最终 `src` 被设置为最后一个候选路径（不存在），跳过了中间正确的路径。

```javascript
// ❌ 旧代码：所有语句都会执行，最后一个覆盖前面的
onerror="if(...){this.src='path1'};if(...){this.src='path2'};if(...){this.src='path3'}"
```

### 解决方案
改用数组+递增索引方式，每次 onerror 只尝试下一个候选：

```javascript
// ✅ 新代码：用 dataset.fi 记录当前索引，每次只尝试下一个
onerror="var a=['path1','path2'],i=+(this.dataset.fi||0);if(i<a.length){this.dataset.fi=i+1;this.src=a[i]}else{this.style.display='none'}"
```

---

## 5. 剧本内容不显示

### 现象
切换到「剧本」标签页，内容完全空白。

### 根因
两个项目的 `02-screenplay.json` 格式不一致：

| 项目 | 格式 |
|------|------|
| 龙脉 | `[ { clip_id, scenes } ]` — 直接是数组 |
| 零号频率 | `{ "clips": [ { clip_id, scenes } ] }` — 对象包裹数组 |

`renderScreenplay()` 中 `Array.isArray(screenplay)` 对对象返回 `false`，直接走了空数组。

另外，`renderScreenplay` 只取 `sp.scenes?.[0]`（第一个 scene），多 scene 的 clip 会丢失后续 scene。

### 解决方案

1. **`loadEpisode` 中加入格式归一化**：
```javascript
if (!Array.isArray(screenplay)) {
  screenplay = screenplay?.clips || [];
}
```

2. **`renderScreenplay` 支持多 scene 渲染**：遍历所有 scene，用虚线分隔。

---

## 6. 本地 Mac 无法访问远程服务器页面

### 现象
在本地 Mac 浏览器访问 `http://localhost:8899/viewer.html`，页面毫无变化或无法加载。

### 根因
服务器运行在远程云开发机 `allenyulin.devcloud.woa.com`（IP: `21.214.50.151`）上，本地 Mac 的 `localhost:8899` 并没有连通到远程服务器。

看到的"没变化的页面"是浏览器缓存的旧页面，或 VS Code 端口转发缓存的旧响应。

### 解决方案

**方案一：SSH 端口转发**（推荐）：
```bash
ssh -p 36000 -L 8899:127.0.0.1:8899 allenyulin@allenyulin.devcloud.woa.com
```
然后访问 `http://localhost:8899/viewer.html`

**方案二：内网直连**（需在同一内网）：
```
http://21.214.50.151:8899/viewer.html
```

**方案三：VS Code 端口转发**：
1. PORTS 面板中删除已有的 8899 端口转发
2. 重新添加 8899 端口
3. 右键 → Port Visibility → Public

---

## 7. SSH 端口转发失败

### 现象
```
ssh -L 8899:127.0.0.1:8899 allenyulin@allenyulin.devcloud.woa.com
Connection closed by 21.214.50.151 port 22
```

### 根因
云开发机的 SSH 端口是 **36000**，不是默认的 22。

### 解决方案
加上 `-p 36000` 参数：
```bash
ssh -p 36000 -L 8899:127.0.0.1:8899 allenyulin@allenyulin.devcloud.woa.com
```

---

## 快速参考

### 启动开发服务器
```bash
cd /data/workspace/waoowaoo/seedance
python3 serve.py 8899
```

### 本地 Mac 访问（SSH 端口转发）
```bash
ssh -p 36000 -L 8899:127.0.0.1:8899 allenyulin@allenyulin.devcloud.woa.com
# 然后浏览器打开 http://localhost:8899/viewer.html
```

### 关键文件
| 文件 | 说明 |
|------|------|
| `viewer.html` | 主页面（1550+ 行） |
| `serve.py` | 无缓存 HTTP 开发服务器 |
| `.agent-state.json` | 项目/集数状态管理 |
| `projects/{项目名}/assets/` | 角色、场景、道具 JSON + 图片 |
| `projects/{项目名}/outputs/{集数}/` | 剧本、分镜、台词等输出文件 |
