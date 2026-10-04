/**
 * 自检：busy 状态的兜底看门狗。
 *
 * 为什么需要它：用户报"停下来只有一个动作"。实测原因是宠物卡在
 * `workStatus=工作状态-忙碌点按` 再没回到 idle——`sendMood('busy')` 之后能清掉它的
 * 只有 `tools/result` 的 4 秒衰减、或 `agent/status idle`。一轮若以错误/中断结尾，
 * 两者都可能不来，于是永久卡住。这个看门狗就是那个"永久"的兜底。
 *
 * 这里用极短的 `busyWatchdogSec` 来验证它确实会触发，并验证**有真实活动时会撤销**。
 *
 *     node tools/test_busy_watchdog.mjs
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

const PORT = 8923;          // 假装是桌宠的显示服务，收 /mood
// 注意别用 8899：那是**真桌宠**在监听的端口，会 EADDRINUSE（第一版就是这么失败的）。
const results = [];
const check = (label, ok, detail = '') => {
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? '  ' + detail : ''}`);
  results.push(ok);
};

// 假的桌宠：记录收到的所有 /mood
const moods = [];
const petServer = http.createServer((req, res) => {
  let body = '';
  req.on('data', (c) => { body += c; });
  req.on('end', () => {
    if (req.url?.startsWith('/mood')) {
      try { moods.push(JSON.parse(body || '{}').mood); } catch { moods.push('?'); }
    }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{"ok":true}');
  });
});
await new Promise((r) => petServer.listen(PORT, '127.0.0.1', r));

// 收集插件注册的事件处理器，便于手动触发
const handlers = new Map();
const ctx = {
  on(name, fn) {
    if (!handlers.has(name)) handlers.set(name, []);
    handlers.get(name).push(fn);
  },
  logger: { warn() {}, info() {} },
  get() { return undefined; },
  llm: { stream: async function* () { yield { type: 'finish', reason: 'stop' }; } },
};

const fire = (name, ...args) => (handlers.get(name) || []).forEach((fn) => fn(...args));

// 看门狗设成 1 秒，免得测试等 90 秒
plugin.apply(ctx, { petPort: PORT, selfPort: 8921, busyWatchdogSec: 1 });
await new Promise((r) => setTimeout(r, 500));

console.log('  -- 工具调用后进入 busy --');
moods.length = 0;
fire('session/event', null, { type: 'tool/call' });
await new Promise((r) => setTimeout(r, 300));
check('收到 busy', moods.includes('busy'), `moods=${JSON.stringify(moods)}`);

console.log('  -- 没有后续事件时，看门狗把它拨回 idle --');
moods.length = 0;
await new Promise((r) => setTimeout(r, 1600));
check('看门狗触发并发出 idle', moods.includes('idle'), `moods=${JSON.stringify(moods)}`);

console.log('  -- 有真实活动时，看门狗要被撤销 --');
moods.length = 0;
fire('session/event', null, { type: 'tool/call' });      // 开始 busy（安排看门狗）
await new Promise((r) => setTimeout(r, 200));
fire('session/event', null, { type: 'tool/result' });    // 有结果 -> clearBusy
moods.length = 0;
await new Promise((r) => setTimeout(r, 1600));
check('工具返回后看门狗不再误报 idle', !moods.includes('idle'), `moods=${JSON.stringify(moods)}`);

console.log('  -- 一轮正常结束时也要回到 idle --');
moods.length = 0;
fire('session/event', null, { type: 'tool/call' });
await new Promise((r) => setTimeout(r, 200));
fire('agent/status', { status: 'idle' });
// 这一轮用过工具，所以会先走 `celebrating`（FLASH_MS = 6 秒）再回 idle——
// 不能只等 300ms 就断言 idle（第一版就是这么误判的）。
await new Promise((r) => setTimeout(r, 7000));
check('agent/status idle 最终回到 idle', moods.includes('idle'),
      `moods=${JSON.stringify(moods)}`);
check('途中经过 celebrating（干完活的反馈）', moods.includes('celebrating'),
      `moods=${JSON.stringify(moods)}`);

petServer.close();
console.log(results.every(Boolean) ? '全部通过' : `失败 ${results.filter((x) => !x).length} 项`);
process.exit(0);
