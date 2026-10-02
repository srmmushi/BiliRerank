"""Chinese / English strings.

Log entries only ever carry a key plus its arguments, so everything the user
sees can be re-rendered when the language changes. This module is UI-agnostic:
the terminal printer (core.log) renders the same keys.
"""

STRINGS = {
    "zh": {
        "raw": "{text}",
        "tag.hot": "互动高",
        "tag.length": "时长好",
        "tag.fresh": "新片",
        "tag.clickbait": "标题党",
        "tag.spam": "疑似带货",
        "tag.short": "过短",
        "tag.low_eng": "互动偏低",
        "tag.authority": "大UP",
        "tag.title_good": "标题清晰",
        "tag.trending": "上升中",
        "tag.interest": "兴趣匹配",
        "inject.start": "开始注入",
        "inject.cdp_ok": "DevTools 已接管，客户端里的推荐流会被直接改写",
        "inject.fallback": "DevTools 没接上，无法改写客户端",
        "rr.done": "推荐流 {seen} 条 → 保留 {kept} 条（广告 {ads}，竖屏 {vertical}，顺延 {deferred}），最高分 {top}",
        "rr.added": "新加入 {added} 条，列表累计 {total} 条",
        "rr.head": "前三位：{list}",
        "rr.cleared": "客户端刷新，列表重新开始",
        "rr.feed_list": "本次获取到的视频（{n}）：\n{list}",
        "cdp.connecting": "正在探测调试端口 {port}",
        "cdp.port_open": "调试端口 {port} 已经在监听",
        "cdp.restarting": "客户端在跑但没开调试端口，正在重启并加上 --remote-debugging-port={port}",
        "cdp.no_port": "客户端在运行，但没开调试端口 {port}：请给客户端快捷方式加上 --remote-debugging-port={port}",
        "cdp.not_running": "{process} 没有在运行，启动客户端后会自动注入",
        "cdp.no_exe": "没找到客户端可执行文件，请手动启动一次",
        "cdp.launching": "启动客户端：{exe}（端口 {port}）",
        "cdp.launch_failed": "启动客户端失败：{err}",
        "cdp.port_ready": "调试端口 {port} 已就绪",
        "cdp.port_timeout": "等待调试端口 {port} 超时（{secs}s）",
        "cdp.kill_failed": "结束旧进程失败：{err}",
        "cdp.no_target": "调试端口上没有可用的页面目标",
        "cdp.attached": "已接管页面：{title}",
        "cdp.intercepting": "已开启响应拦截（{n} 个页面，端口 {port}）",
        "cdp.not_feed": "跳过非推荐流响应：{url}",
        "cdp.body_failed": "读取响应体失败：{err}",
        "cdp.fulfill_failed": "回写失败：{err}",
        "cdp.continue_failed": "放行响应失败：{err}",
        "cdp.error": "DevTools 出错：{err}",
        "cdp.closed": "DevTools 连接已结束",
        "cdp.no_websockets": "缺少 websockets 库：pip install websockets",
        "cdp.already": "DevTools 已经在运行",
        "watch.up": "检测到客户端已启动",
        "watch.down": "客户端已退出，停止注入",
        "watch.error": "客户端监听出错：{err}",
        "py.back_done": "已回到上一次刷新的 {n} 条",
        "py.back_empty": "没有可回退的列表",
        "cli.banner": "BiliRerank {version} · 终端模式",
        "cli.lang": "语言：{lang}",
        "cli.debug": "调试等级：{level} / 7",
        "cli.algorithm": "算法：{name}",
        "cli.boot_enabled": "已设置为开机自启（后台运行）。下次登录时将自动注入。",
        "cli.boot_disabled": "已取消开机自启。",
        "cli.boot_failed": "设置开机自启失败：{err}",
        "cli.starting": "正在监听客户端，出现后自动注入（Ctrl+C 退出并取消注入）...",
        "cli.stop": "正在取消注入并退出 ...",
        "cli.client_missing": "提示：客户端尚未运行，启动后本程序会自动接管。",
        "algo.weighted.on": "重排算法：八维加权（基线）",
        "algo.gnn.on": "重排算法：图神经网络重排（GNN · Personalized PageRank）",
        "algo.bandit.on": "重排算法：上下文老虎机（LinUCB）",
        "algo.mmr.on": "重排算法：MMR + 子模优化",
        "algo.sequential.on": "重排算法：序列建模（GRU4Rec 式）",
        "algo.pareto.on": "重排算法：多目标帕累托优化（NSGA-II）",
        "algo.counterfactual.on": "重排算法：反事实推断（IPS / Doubly Robust）",
        "algo.unknown.on": "未知算法：{name}，已回退到基线",
        "algo.fail": "算法 {name} 执行出错：{err}，已回退基线",
        "play.now": "正在播放：{title}（{bvid}）",
    },
    "en": {
        "raw": "{text}",
        "tag.hot": "engaged",
        "tag.length": "good length",
        "tag.fresh": "fresh",
        "tag.clickbait": "clickbait",
        "tag.spam": "ad-ish",
        "tag.short": "too short",
        "tag.low_eng": "low engagement",
        "tag.authority": "big UP",
        "tag.title_good": "clear title",
        "tag.trending": "trending",
        "tag.interest": "interest match",
        "inject.start": "injecting",
        "inject.cdp_ok": "DevTools took over, the feed inside the client is rewritten in place",
        "inject.fallback": "DevTools did not connect, the client cannot be rewritten",
        "rr.done": "feed {seen} -> kept {kept} (ads {ads}, vertical {vertical}, deferred {deferred}), top score {top}",
        "rr.added": "{added} new, {total} in the list",
        "rr.head": "top three: {list}",
        "rr.cleared": "client refreshed, the list starts over",
        "rr.feed_list": "videos fetched this round ({n}):\n{list}",
        "cdp.connecting": "probing debug port {port}",
        "cdp.port_open": "debug port {port} is already listening",
        "cdp.restarting": "the client is running without a debug port - restarting it with --remote-debugging-port={port}",
        "cdp.no_port": "the client runs without debug port {port}: add --remote-debugging-port={port} to its shortcut",
        "cdp.not_running": "{process} is not running - injection starts by itself once it does",
        "cdp.no_exe": "client executable not found - start it once by hand",
        "cdp.launching": "launching the client: {exe} (port {port})",
        "cdp.launch_failed": "cannot launch the client: {err}",
        "cdp.port_ready": "debug port {port} is ready",
        "cdp.port_timeout": "timed out waiting for debug port {port} ({secs}s)",
        "cdp.kill_failed": "cannot stop the old process: {err}",
        "cdp.no_target": "no page target on the debug port",
        "cdp.attached": "attached to page: {title}",
        "cdp.intercepting": "response interception is on ({n} pages, port {port})",
        "cdp.not_feed": "skipping a non-feed response: {url}",
        "cdp.body_failed": "cannot read the response body: {err}",
        "cdp.fulfill_failed": "cannot write the response back: {err}",
        "cdp.continue_failed": "cannot let the response through: {err}",
        "cdp.error": "DevTools error: {err}",
        "cdp.closed": "DevTools session ended",
        "cdp.no_websockets": "websockets is missing - pip install websockets",
        "cdp.already": "DevTools is already running",
        "watch.up": "client detected",
        "watch.down": "client closed, injection stopped",
        "watch.error": "client watcher failed: {err}",
        "py.back_done": "back to the {n} items from before the refresh",
        "py.back_empty": "nothing to go back to",
        "cli.banner": "BiliRerank {version} · terminal mode",
        "cli.lang": "language: {lang}",
        "cli.debug": "debug level: {level} / 7",
        "cli.algorithm": "algorithm: {name}",
        "cli.boot_enabled": "Auto-start on logon enabled (runs in background). Injection will begin automatically next time you sign in.",
        "cli.boot_disabled": "Auto-start on logon disabled.",
        "cli.boot_failed": "could not set auto-start: {err}",
        "cli.starting": "Watching for the client; injecting automatically when it appears (Ctrl+C to stop and cancel injection) ...",
        "cli.stop": "Cancelling injection and exiting ...",
        "cli.client_missing": "Hint: the client is not running yet. It will be taken over automatically once started.",
        "algo.weighted.on": "rerank: weighted 8-dimension (baseline)",
        "algo.gnn.on": "rerank: GNN (Personalized PageRank over a similarity graph)",
        "algo.bandit.on": "rerank: Contextual Bandit (LinUCB)",
        "algo.mmr.on": "rerank: MMR + Submodular greedy",
        "algo.sequential.on": "rerank: Sequential model (GRU4Rec-style)",
        "algo.pareto.on": "rerank: Multi-Objective Pareto (NSGA-II)",
        "algo.counterfactual.on": "rerank: Counterfactual (IPS / Doubly Robust)",
        "algo.unknown.on": "unknown algorithm: {name}, fell back to baseline",
        "algo.fail": "algorithm {name} failed: {err}, fell back to baseline",
        "play.now": "now playing: {title} ({bvid})",
    },
}

LANGS = ("zh", "en")


class Translator:
    def __init__(self, lang="zh"):
        self.lang = lang if lang in LANGS else LANGS[0]

    def set(self, lang):
        self.lang = lang if lang in LANGS else LANGS[0]
        return self.lang

    def t(self, key, args=None):
        template = STRINGS[self.lang].get(key)
        if template is None:
            return key
        if not args:
            return template
        try:
            return template.format(**args)
        except (KeyError, IndexError, ValueError):
            return template
