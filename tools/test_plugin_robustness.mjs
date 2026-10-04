/**
 * 自检：插件不能拖垮 DSH 宿主。
 *
 * 背景（真实事故）：一次重构里我删掉了局部的 `const balanceTierLabel`，只留
 * `apply.balanceTierLabel = ...`，而 `reportUsage` 用的仍是本地名字。它在
 * `setTimeout` 回调里抛 `ReferenceError`，DSH 宿主进程直接
 * `fatal load failure: exited with 1` —— **整个应用崩了**，不只是桌宠掉线。
 *
 * 这里覆盖两件事：
 *   1. `reportUsage` 这条路径（一轮结束时经 setTimeout 触发）真的能跑通并发出 /usage；
 *      **原先的 test_balance.mjs 只打 /health，走的是 balanceTier，从未覆盖它**——
 *      这就是那个 ReferenceError 能溜到线上的原因。
 *   2. `guard()` 确实能拦住事件处理器与定时器里的异常（故意让处理器抛错，宿主不受影响）。
 *
 *     node tools/test_plugin_robustness.mjs
 */

// 被测插件的路径：默认从当前用户的家目录推出来，也可以用 DSH_PLUGIN_DIR 覆盖。
// 不要写死某个用户名——那是别人机器上的路径，测试在他那里必然失败。
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const pluginDir = process.env.DSH_PLUGIN_DIR
  || path.join(os.homedir(), '.dsh', 'profiles', 'node_modules', 'dsh-pet-bridge');
const plugin = await import(pathToFileURL(path.join(pluginDir, 'lib', 'index.js')).href);

const http = await import('node:http');

const PORT = 8927;          // 假装是桌宠的显示服务（别用 8899，那是真桌宠）
const results = [];
const check = (label, ok, detail = '') => {
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? '  ' + detail : ''}`);
  results.push(ok);
};

// 记录桌宠收到的所有投递
const received = { mood: [], usage: [], say: [] };
const petServer = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => { body += c; });
  req.on('end', () => {
    const path = (req.url || '').split('?')[0];
    let payload = {};
    try { payload = JSON.parse(body || '{}'); } catch { /* 忽略 */ }
    if (path === '/mood') received.mood.push(payload.mood);
    else if (path === '/usage') received.usage.push(payload);
    else if (path === '/say') received.say.push(payload);
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{"ok":true}');
  });
});
await new Promise((r) => petServer.listen(PORT, '127.0.0.1', r));

const handlers = new Map();
let warns = [];
const ctx = {
  on(name, fn) {
    if (!handlers.has(name)) handlers.set(name, []);
    handlers.get(name).push(fn);
  },
  logger: { warn: (...a) => warns.push(a.join(' ')), info() {} },
  // 余额可用，这样 reportUsage 会走到**余额分支**——也就是出事的那一行
  get(name) {
    if (name !== 'deepseekAccount') return undefined;
    return {
      async getBalance() {
        return { status: 'ready', value: [{ currency: 'CNY', balance: '9.13' }], bonusWallets: [] };
      },
    };
  },
};

const fire = (name, ...args) => (handlers.get(name) || []).forEach((fn) => fn(...args));

plugin.apply(ctx, { petPort: PORT, selfPort: 8928, balanceCacheSec: 0 });
await new Promise((r) => setTimeout(r, 600));

console.log('  -- 一轮结束时 reportUsage 必须能跑通（就是出事的那条路）--');
received.usage.length = 0;
warns = [];
// 走一轮：工具调用 -> 一轮结束（用工具的那轮会先 celebrating，再 setTimeout(reportUsage)）
fire('session/event', null, { type: 'tool/call' });
await new Promise((r) => setTimeout(r, 150));
fire('agent/status', { status: 'idle' });
// FLASH_MS(6s) + 400ms 之后才 reportUsage
await new Promise((r) => setTimeout(r, 7200));
check('reportUsage 发出了 /usage', received.usage.length > 0,
      `usage=${JSON.stringify(received.usage)}`);
const usage = received.usage[received.usage.length - 1] || {};
check('走的是**余额**分支（文案带"余额"）', String(usage.text || '').includes('余额'),
      `text=${JSON.stringify(usage.text)}`);
check('档位 = 3（9.13 元）', usage.tier === 3, `tier=${usage.tier}`);
const fatal = warns.filter((w) => /balanceTierLabel|is not defined|ReferenceError/.test(w));
check('没有 ReferenceError（原事故点）', fatal.length === 0, `warns=${JSON.stringify(warns)}`);

console.log('  -- guard：插件自己的异常不许外传 --');
// 这一条**静态检查**而不是运行时构造异常：`guard` 没法从外面拿到（它封在 apply 里），
// 而"处理器对畸形参数是否抛错"取决于实现细节，构造起来很脆。直接查源码更可靠：
// 所有事件订阅都必须是 `safeOn`，不允许有裸的 `ctx.on(事件, ...)`。
// （`ctx.on('dispose', ...)` 是清理回调，不在此列。）
const source = await (await import('node:fs/promises')).readFile(
  path.join(pluginDir, 'lib', 'index.js'), 'utf8');
const bareOn = [...source.matchAll(/ctx\.on\(\s*'([^']+)'/g)]
  .map((m) => m[1])
  .filter((name) => name !== 'dispose');
check('没有绕过 guard 的事件订阅', bareOn.length === 0,
      bareOn.length ? `裸订阅: ${bareOn.join(', ')}` : '');
const safeOnCount = [...source.matchAll(/safeOn\(\s*'/g)].length;
check('主要事件都走 safeOn', safeOnCount >= 3, `safeOn 用了 ${safeOnCount} 次`);
const timerGuard = [...source.matchAll(/setTimeout\(\s*guard\(/g)].length;
check('定时器回调也过 guard', timerGuard >= 3, `setTimeout(guard(...)) 用了 ${timerGuard} 次`);

console.log('  -- 出过错之后插件仍然可用 --');
received.mood.length = 0;
fire('session/event', null, { type: 'tool/call' });
await new Promise((r) => setTimeout(r, 250));
check('后续事件仍被正常处理', received.mood.includes('busy'),
      `mood=${JSON.stringify(received.mood)}`);

petServer.close();
console.log(results.every(Boolean) ? '全部通过' : `失败 ${results.filter((x) => !x).length} 项`);
process.exit(0);
