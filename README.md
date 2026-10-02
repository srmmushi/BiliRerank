# BiliHook

B站 Windows 客户端的**推荐流本地重排**工具：接管客户端首页的推荐流响应，按本地策略过滤与排序后再送回列表，全过程在本机完成，不转发、不上传任何数据。

- 界面：PyQt5 + PyQt-SiliconUI（粉色主题，深色/浅色，中英双语）
- 改写：Chrome DevTools 协议（拦截响应体并重排后回写）
- 旁挂：frida 只读钩子（可选，用于观察，不改写）
- 全自动：客户端一出现就注入，退出即停止

## 目录

```
main.py                     入口
requirements.txt
src/
├─ core/     config  settings  store  rerank       配置、状态、评分算法
├─ backends/ devtools  frida_hook                  传输层（改写 / 旁挂）
└─ ui/       app  pages  widgets  theme  icons  icon  editor  i18n
src/assets/scripts/rcmd.js  随程序分发的内置脚本
```

运行期生成（不在仓库里）：`settings.json`、`<配置目录>/script/`、`icon.ico`。

## 安装与运行

```powershell
# 依赖
C:\app\Python313\python.exe -m pip install -r requirements.txt

# PyQt-SiliconUI 还没上 PyPI，单独装一次
C:\app\Python313\python.exe -m pip install "git+https://github.com/ChinaIceF/PyQt-SiliconUI"

# 运行
C:\app\Python313\python.exe main.py
```

Windows 10/11 + Python 3.10+。首次启动会把内置脚本释放到配置目录、生成任务栏图标。

## 怎么用

1. 打开 B站客户端，工具检测到后自动注入（右上角状态灯变绿）；
2. 客户端首页下拉刷新，推荐流会被本地重排：过滤广告与竖屏、互动/时长打分、同一 UP 去重顺延；
3. 刷新后顶栏出现 **← 回退**，点一下回到上一次刷新前的列表；
4. 想手动控制：右上角 **注入 / 停止**。

四个页面：

| 页面 | 内容 |
|---|---|
| 推荐流 | 重排后的卡片：排名、标题、UP、mid、分数 |
| 脚本列表 | 每个脚本一行：注入 / 停止 / 日志 / 修改 / 删除 |
| 日志 | 分级着色控制台，可按脚本过滤 |
| 设置 | 主题、语言、随客户端自动注入、重启客户端、配置文件位置 |

## 配置与脚本

- 配置文件默认在程序目录下的 `settings.json`；设置页可以**改到别的位置**（会记在 `.settings-path` 里，改回默认即删除该指针）；
- 脚本目录跟随配置文件：`<配置目录>/script/`。启动时把内置脚本释放进去，**已存在的不覆盖**；内置脚本被删掉后下次启动会重新释放；
- 脚本列表里可以改、删单个脚本；保存后如果脚本正在运行会自动重载；
- 任务栏图标放在配置目录，扔一个自己的 `icon.ico` / `icon.png` 进去即替换（默认图标是程序用 Pillow 画的“小电视 + 钩子”）。

## 它是怎么工作的

- **devtools**：客户端带 `--remote-debugging-port=9222` 启动时，工具连接每个页面，`Fetch` 阶段拦截响应体；命中推荐流 URL 就用 `rerank` 重排并 `fulfill` 回写（`rewritten` 计数），其余请求原样放行。客户端没开调试端口时，设置页的“重启客户端”会带上参数重启它；
- **frida**：附加到进程并加载脚本目录下的脚本，只做观察与上报（frida 的回调是异步的，改写的响应到达时调用方已经消费完原始数据，所以改写只能由 devtools 完成）。两边同时抓到的卡片按 bvid 去重；
- **评分**（`core/rerank.py`）：互动率、时长甜区、新鲜度、VOD 加分，标题党/带货/过短/低互动/超长扣分，同一 UP 超过 N 条顺延。

Electron 版客户端没有原生导出，frida 一侧通常会报 `js.no_target`——这是预期的，重排仍由 devtools 完成。

## 常见问题

- **日志停在“没有找到可挂的目标函数”**：正常，见上；重排不看这条。
- **客户端没开调试端口**：设置页点“重启客户端”，或给快捷方式加 `--remote-debugging-port=9222`。
- **附加失败**：frida 与客户端位数要一致（都是 64 位），必要时用管理员权限运行。
- **界面里中文是方块/发虚**：程序已固定用平滑字体（微软雅黑 UI / Cascadia Mono），图标用系统图标字体绘制；如仍异常，检查显示缩放是否被强制成非整数倍。

## 许可

本项目代码采用 **MIT**（见 `LICENSE`）。注意：它依赖的 PyQt-SiliconUI 是 **GPL-3.0**，随发行版一起分发时需要遵循 GPL；去掉该依赖即为纯 MIT。

仅供学习交流，请勿用于违反平台用户协议的用途。
