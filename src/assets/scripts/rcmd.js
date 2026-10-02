'use strict';

// biliRerank - frida probe for the bilibili desktop client.
//
// What this script does: it finds the feed function, reads the JSON it returns
// and forwards the raw text to Python. Scoring and reordering live in core.py,
// so there is exactly one implementation of the algorithm.
//
// What it cannot do: rewrite the response. Frida callbacks are asynchronous, so
// the modified body would arrive after the caller already consumed the original.
// The CDP backend is the one that writes the feed back.
//
// Recent clients are Electron based (哔哩哔哩.exe + a packed .tmp.node addon), so
// there is usually no native export to hook. TARGET is a guess until you check:
//
//   frida-trace -n 哔哩哔哩.exe -i "*rcmd*"
//   frida-trace -n 哔哩哔哩.exe -i "*feed*" -i "*recommend*"
//
// Then either fill TARGET.symbol, set a static TARGET.offset, or leave
// TARGET.keyword to let the script list the candidates it can see.

const TARGET = {
    module: 'bilibili.dll',   // exact name, or a case-insensitive regex source
    symbol: null,
    offset: null,
    keyword: 'rcmd',
};

const FEED_MARKERS = ['"rcmd_reason"', '"items":[', '"item":[', '"goto":"av"'];
const DEDUPE_MS = 1500;       // the same payload often comes twice per refresh

const stats = { calls: 0, feeds: 0, skipped: 0 };
const warned = {};
let listener = null;
let lastHash = '';

function emit(level, key, args) {
    send({ type: 'log', level: level, key: key, args: args || {} });
}

function emitOnce(id, level, key, args) {
    if (warned[id]) return;
    warned[id] = true;
    emit(level, key, args);
}

// TARGET.module is only a guess until the process is inspected, so report what
// is really loaded - System32 noise skipped, export counts included.
function listModules() {
    const mods = Process.enumerateModules()
        .filter(m => !/^[A-Za-z]:\\Windows\\/i.test(m.path));
    const parts = [];
    for (let i = 0; i < mods.length && i < 12; i++) {
        let count = -1;
        try { count = mods[i].enumerateExports().length; } catch (e) { /* packed */ }
        parts.push(mods[i].name + ' (exports ' + count + ')');
    }
    return parts.join(', ') || '-';
}

function findModule() {
    const exact = Process.findModuleByName(TARGET.module);
    if (exact) return exact;
    try {
        const re = new RegExp(TARGET.module, 'i');
        return Process.enumerateModules().find(m => re.test(m.name)) || null;
    } catch (e) {
        return null;
    }
}

function listCandidates(keyword) {
    const mod = findModule();
    if (!mod) {
        emit('error', 'js.module_missing', { module: TARGET.module, loaded: listModules() });
        return;
    }
    const names = mod.enumerateExports()
        .filter(e => e.name.toLowerCase().indexOf(keyword) !== -1)
        .map(e => e.name);
    emit('warn', 'js.candidates', {
        keyword: keyword,
        module: mod.name,
        names: names.slice(0, 20).join(', ') || '-',
    });
    if (!names.length) emit('info', 'js.modules', { modules: listModules() });
}

function resolveTarget() {
    if (TARGET.offset !== null) {
        const mod = findModule();
        if (!mod) {
            emit('error', 'js.module_missing', { module: TARGET.module, loaded: listModules() });
            return null;
        }
        return mod.base.add(TARGET.offset);
    }
    if (TARGET.symbol) {
        const mod = findModule();
        const addr = mod ? mod.findExportByName(TARGET.symbol) : null;
        if (!addr) emit('error', 'js.export_missing', { symbol: TARGET.symbol });
        return addr;
    }
    if (TARGET.keyword) listCandidates(TARGET.keyword);
    return null;
}

// The feed function either hands back a raw char* or an MSVC std::string*
// (layout: pointer-to-buffer / inline[16], then size, then capacity - short
// strings live inside the object itself).
function readStdString(p) {
    const size = p.add(Process.pointerSize).readU64().toNumber();
    const cap = p.add(Process.pointerSize * 2).readU64().toNumber();
    if (size === 0 || size > 8 * 1024 * 1024) return null;
    if (cap > 15) {
        const buf = p.readPointer();
        return buf.isNull() ? null : buf.readUtf8String(size);
    }
    return p.readUtf8String(size);
}

function looksLikeJson(text) {
    if (!text || text.length < 2) return false;
    const c = text.charAt(0);
    return c === '{' || c === '[';
}

function looksLikeFeed(text) {
    for (let i = 0; i < FEED_MARKERS.length; i++) {
        if (text.indexOf(FEED_MARKERS[i]) !== -1) return true;
    }
    return false;
}

function readReturn(retval) {
    if (retval.isNull()) return null;

    let text = null;
    try { text = retval.readCString(); } catch (e) { /* not a c string */ }
    if (looksLikeJson(text)) return text;

    try { text = readStdString(retval); } catch (e) { /* not a std::string */ }
    return looksLikeJson(text) ? text : null;
}

function hash(text) {
    let h = 0;
    const step = text.length > 4096 ? 97 : 1;   // sample big payloads, keep it cheap
    for (let i = 0; i < text.length; i += step) h = (h * 31 + text.charCodeAt(i)) | 0;
    return h + ':' + text.length;
}

function onLeave(retval) {
    stats.calls++;
    try {
        const text = readReturn(retval);
        if (!text) {
            emitOnce('shape', 'warn', 'js.bad_shape');
            return;
        }

        if (!looksLikeFeed(text)) {
            stats.skipped++;
            emitOnce('shape', 'warn', 'js.bad_shape');
            return;
        }

        const id = hash(text);
        const now = Date.now();
        if (id === lastHash && now - (this.t || 0) < DEDUPE_MS) {
            stats.skipped++;
            return;
        }
        this.t = now;
        lastHash = id;

        emitOnce('hit', 'success', 'js.hit');
        send({ type: 'feed', raw: text });
    } catch (e) {
        emit('error', 'js.onleave_error', { err: String(e.message || e) });
    }
}

function start() {
    if (listener !== null) {
        emit('warn', 'js.already');
        return false;
    }
    const addr = resolveTarget();
    if (!addr) {
        emit('error', 'js.no_target');
        return false;
    }
    try {
        listener = Interceptor.attach(addr, { onLeave: onLeave });
    } catch (e) {
        emit('error', 'js.attach_failed', { addr: String(addr), err: String(e.message || e) });
        listener = null;
        return false;
    }
    emit('success', 'js.installed', { addr: String(addr), module: TARGET.module });
    return true;
}

function stop() {
    if (listener === null) return false;
    try { listener.detach(); } catch (e) { /* already gone */ }
    listener = null;
    emit('info', 'js.detached');
    return true;
}

rpc.exports = {
    start: start,
    stop: stop,
    stats: function () { return stats; },
    probe: listCandidates,
    modules: listModules,
};

emit('info', 'js.loaded', { version: Frida.version, arch: Process.arch });
start();
// note
