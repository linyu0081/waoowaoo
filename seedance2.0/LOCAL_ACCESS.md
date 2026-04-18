> 最后更新：2026-04-19

Dashboard 页面 `dashboard.html` 部署在**远程云开发机**（`allenyulin@allenyulin.devcloud.woa.com`，内网 IP `21.214.73.158`），本地 Mac 不能直接访问 `http://localhost:8765`，需要先建立网络通路。

---

## 🌐 服务端信息（供参考）

| 项 | 值 |
|---|---|
| 云开发机用户名 | `allenyulin` |
| SSH 主机名 | `allenyulin.devcloud.woa.com` |
| SSH 端口 | **36000**（非默认 22） |
| 内网 IP | `21.214.73.158` |
| Dashboard 文件 | `/data/workspace/waoowaoo/seedance2.0/dashboard.html` |
| 服务端口 | `8765` |
| 服务实现 | `serve.py`（无缓存 `Cache-Control: no-store`） |
| 守护进程 | `systemctl --user` 管理的 `seedance-dashboard.service` |

---

## 🚀 方案 A（推荐）：SSH 端口转发

**最稳**，完全绕过 VSCode 端口转发层的缓存问题。

### 1. 在**本地 Mac 终端**建立隧道

```bash
ssh -p 36000 -L 8765:127.0.0.1:8765 allenyulin@allenyulin.devcloud.woa.com
```

- `-p 36000`：指定 SSH 端口（⚠️ 必须，不是 22）
- `-L 8765:127.0.0.1:8765`：把本地 8765 转发到远端 `127.0.0.1:8765`
- 登录成功后**窗口保留不关**（关了隧道就断）

### 2. 本地浏览器打开

👉 **http://localhost:8765/dashboard.html**

### 3.（可选）后台保活

如果不想每次都开终端窗口，可以加 `-fNT` 让隧道在后台跑：

```bash
ssh -fNT -p 36000 -L 8765:127.0.0.1:8765 allenyulin@allenyulin.devcloud.woa.com
```

停掉这个后台隧道：

```bash
# 找到进程然后 kill
ps aux | grep "ssh.*8765" | grep -v grep
# 或者直接
pkill -f "ssh.*-L 8765"
```

### 4.（可选）配置 `~/.ssh/config` 简化

```
Host devcloud
    HostName allenyulin.devcloud.woa.com
    Port 36000
    User allenyulin
    LocalForward 8765 127.0.0.1:8765
    ServerAliveInterval 30
    ServerAliveCountMax 3
```

然后只需：`ssh devcloud` 即可建立隧道。

---

## 🏢 方案 B：内网直连（仅限公司网络/VPN）

如果你本地 Mac 通过公司网络或 VPN，可以直通 `21.214.50.151`：

👉 **http://21.214.73.158:8765/dashboard.html**

外网环境用不了，直接走方案 A。

---

## 💻 方案 C：VSCode Remote 端口转发（不推荐）

VSCode 的端口转发会在浏览器侧做重度缓存，即使服务端已带 `no-store`，VSCode 自己的代理层也可能返回旧内容，表现为**打开空白页**。

如果确实要用：

1. VSCode 底部 `PORTS` 面板 → **删除**现有的 8765 转发条目
2. 点 `Forward a Port` → 输入 `8765`
3. 右键端口 → `Port Visibility` → `Public`（否则需要 GitHub 登录）
4. 浏览器打开转发地址后，**Cmd+Shift+R 强制刷新**
5. 如还是空白：`Cmd+Option+I` 打开 DevTools → Network 勾选 **Disable cache** → 再刷新

**终极解法**：在云开发机上换个端口（比如 8899）重启服务，VSCode 转发新端口即可绕开旧缓存：

```bash
systemctl --user stop seedance-dashboard
cd /data/workspace/waoowaoo/seedance2.0
python3 serve.py 8899
```

---

## 🧪 连通性自测

在**本地 Mac 终端**（已建好 SSH 隧道后）：

```bash
curl -sI http://localhost:8765/dashboard.html | head -5
```

**预期输出：**

```
HTTP/1.0 200 OK
Server: SimpleHTTP/0.6 Python/3.6.8
Date: ...
Content-type: text/html
Content-Length: 83970
```

看到 `200 OK` 即连通。如果是 `Connection refused` → 隧道没建或远端服务挂了；`Empty reply` → 远端服务崩了。

---

## 🔧 远端服务运维（在云开发机上执行）

| 操作 | 命令 |
|---|---|
| 查看状态 | `systemctl --user status seedance-dashboard` |
| 启动 | `systemctl --user start seedance-dashboard` |
| 重启 | `systemctl --user restart seedance-dashboard` |
| 停止 | `systemctl --user stop seedance-dashboard` |
| 查看日志 | `journalctl --user -u seedance-dashboard -n 50 --no-pager` |
| 手动前台调试 | `cd /data/workspace/waoowaoo/seedance2.0 && python3 serve.py 8765` |
| 换端口重启 | 先 stop，再 `python3 serve.py 8899` |

首次启动（若 service 不存在）：

```bash
systemd-run --user --unit=seedance-dashboard \
    --description="Seedance2.0 Dashboard (no-cache)" \
    /usr/bin/python3 /data/workspace/waoowaoo/seedance2.0/serve.py 8765
```

---

## 🧯 常见问题

### Q1：浏览器打开就是空白页？
→ 90% 是 VSCode 端口转发层缓存（方案 C）。改用方案 A SSH 隧道，或换端口重启服务。

### Q2：`ssh: connect to host ... port 22: Connection refused`？
→ 忘记加 `-p 36000`，SSH 端口不是默认的 22。

### Q3：`bind: Address already in use`？
→ 本地 8765 已被占用（可能有旧隧道）。

```bash
lsof -i:8765         # 看谁占着
pkill -f "ssh.*-L 8765"   # 杀掉旧的 SSH 转发
```

### Q4：隧道建好但浏览器依然空白？
→ 强制刷新 `Cmd+Shift+R`；或 DevTools 打开后勾选 `Disable cache` 再刷新；再不行换个端口（比如 8899）重启远端服务。

### Q5：每次改完 `dashboard.html` 看不到更新？
→ 服务端已配好 `no-store` 不会缓存；问题一定在客户端/转发层。优先 `Cmd+Shift+R`，再考虑换端口。

---

## 📝 最终推荐姿势（日常用）

```bash
# ~/.ssh/config 里加一次
Host devcloud
    HostName allenyulin.devcloud.woa.com
    Port 36000
    User allenyulin
    LocalForward 8765 127.0.0.1:8765
    ServerAliveInterval 30

# 日常使用
ssh devcloud                                    # 建立隧道+登录
# 新开一个浏览器标签
open http://localhost:8765/dashboard.html       # macOS 一键打开
```

搞定 ✅
