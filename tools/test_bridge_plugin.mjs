/**
 * 用假的 Cordis 上下文 + 假桌宠服务验证 dsh-pet-bridge 的事件映射。
 *
 * 这样可以在不重启 DSH 的前提下，确认"哪种会话事件 → 哪一档 mood"是对的。
 *
 *     node tools/test_bridge_plugin.mjs
 */

import { createServer } from 'node:http';
import { apply, name } from '../plugins/dsh-pet-bridge/lib/index.js';

const received = [];
const server = createServer((req, res) => {
  let body = '';
  req.on('data', (chunk) => {
    body += chunk;
  });
  req.on('end', () => {
    received.push(JSON.parse(body || '{}'));
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end('{"ok":true}');
  });
});

await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;

// 假上下文的订阅表
const handlers = new Map();
const ctx = {
  on(type, handler) {
    if (!handlers.has(type)) handlers.set(type, []);
    handlers.get(type).push(handler);
    return () => {};
  },
};

const fire = (type, ...args) => {
  for (const handler of handlers.get(type) || []) handler(...args);
};

// 假桌宠监听随机端口；插件默认投 8899，所以必须显式告诉它投到哪里
apply(ctx, { petPort: port, selfPort: 0, whisperSec: 0 });

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const steps = [
  ['agent/status running', () => fire('agent/status', { status: 'running' }), 'thinking'],
  ['tools/call', () => fire('session/event', null, { type: 'tools/call' }), 'busy'],
  ['tools/result', () => fire('session/event', null, { type: 'tools/result' }), 'filing'],
  ['approval/asked', () => fire('session/event', null, { type: 'approval/asked' }), 'thinking'],
  ['agent/error', () => fire('agent/error', {}), 'sighing'],
  ['agent/status idle (with tools)', () => fire('agent/status', { status: 'idle' }), 'celebrating'],
];

let failures = 0;
console.log('插件名:', name);

for (const [label, act, expected] of steps) {
  received.length = 0;
  act();
  await wait(220);
  const got = received.length ? received[received.length - 1].mood : '(无请求)';
  const ok = got === expected;
  if (!ok) failures += 1;
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label.padEnd(34)} 期望 ${expected.padEnd(12)} 实得 ${got}`);
}

// 用量分档：idle 之后会延迟补发一条 /usage
console.log('  --- 用量分档 ---');
received.length = 0;
for (let i = 0; i < 12; i += 1) {
  fire('agent/status', { status: 'running' });
  fire('session/event', null, { type: 'tools/result' });
  fire('agent/status', { status: 'idle' });
}
await wait(7000);
const usage = received.filter((item) => item.tier !== undefined);
const okUsage = usage.length > 0;
if (!okUsage) failures += 1;
console.log(`  ${okUsage ? 'OK  ' : 'FAIL'} 用量分档随轮次上报        实得 ${JSON.stringify(usage[usage.length - 1] || null)}`);

server.close();
console.log(failures ? `失败 ${failures} 项` : '全部通过');
process.exit(failures ? 1 : 0);
