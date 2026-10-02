# BiliRerank

B 站 Windows 客户端的**推荐流本地重排**工具：接管客户端首页的推荐流响应，用**图神经网络（GNN · Personalized PageRank）**重排后再送回列表。全过程在本机完成，不转发、不上传任何数据。纯终端运行，无 GUI。

- 改写：Chrome DevTools 协议（拦截响应体并重排后回写）
- 算法：八维打分 + 图神经网络重排（`src/core/algorithms/`）
- 全自动：客户端一出现就注入，退出即停止
- 界面：终端彩色日志（默认中文）

## 目录

```
main.py                     入口
requirements.txt
src/
├─ cli.py                   命令行入口
├─ backends/  devtools.py   传输层（CDP 改写）
└─ core/      config settings store log i18n
              algorithms/   engine（评分引擎）+ 重排算法（gnn 为当前生效）
```

## 安装与运行

```powershell
# 依赖（仅 websockets）
C:\app\Python313\python.exe -m pip install -r requirements.txt

# 运行（默认中文、debug 1）
C:\app\Python313\python.exe main.py
```

Windows 10/11 + Python 3.10+。

## 怎么用

1. 打开 B 站客户端（或用 `schtasks` 让它带 `--remote-debugging-port=9222` 启动）；
2. 运行 `python main.py`，检测到客户端后自动接管，客户端首页下拉刷新即可看到重排后的推荐流；
3. 刷新后顶栏出现 **← 回退**，点一下回到上一次刷新前的列表；
4. `Ctrl+C` 退出并取消注入。

## 命令行参数

```
python main.py [--debug [N]] [--lang zh|en] [--start-on-boot {enable|disable}]
```

| 参数 | 说明 |
|---|---|
| `--debug [N]` | 调试等级 1-7，默认 1；裸 `--debug` = 7（逐视频算法过程）。刷新时会打印本次获取到的全部视频列表 |
| `--lang zh\|en` | 界面/日志语言，默认中文（zh） |
| `--start-on-boot enable\|disable` | 开机自启（后台运行）开关；省略参数默认 enable |

## 重排算法（写死为 GNN）

每个视频先按八个维度打分（互动、时长、新鲜度、作者权威、标题质量、增长动量、兴趣匹配、多样性），再构建相似度图，从高基线分视频与**正在播放的视频**出发跑 Personalized PageRank，按传播后的分数重排，最后做同一 UP 去重顺延。算法固定为 GNN，无运行时切换；其余算法保留在 `src/core/algorithms/` 作为库。

## 它是怎么工作的

- **devtools**：客户端带 `--remote-debugging-port=9222` 启动时，工具连接每个页面，`Fetch` 阶段拦截响应体；命中推荐流 URL 就用重排引擎回写（`rewritten` 计数），其余请求原样放行；
- **评分**（`core/algorithms/engine.py`）：互动率、时长甜区、新鲜度、作者权威、标题党/带货扣分等八维打分；
- **正在播放**：后端周期性读取页面 `location.href` 里的 BV 号，命中当前流中的视频后作为 GNN 的强种子，让重排偏向「接下来想看什么」。

## 许可

本项目代码采用 **MIT**（见 `LICENSE`）。

仅供学习交流，请勿用于违反平台用户协议的用途。
