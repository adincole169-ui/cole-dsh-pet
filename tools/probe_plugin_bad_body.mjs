/**
 * 验证别人补丁里的说法：**插件 `/chat` 收到坏请求会不会带崩 DSH 宿主？**
 *
 * 补丁声称：
 *
 *     插件 /chat 的坏请求会崩 DSH 宿主
 *     原先 unhandled rejection 会让 Node 15+ 退出进程
 *
 * 这条如果成立就非常严重：`JSON.parse('null')` 是合法的，得到 `null`，
 * 之后 `payload.text` 会抛 TypeError —— 而那个回调是 `async`，
 * 抛出的异常没人接 → unhandled rejection → **Node 15+ 默认直接退出进程**，
 * 而那个进程就是 DSH 宿主本身。
 *
 * **绝对不能用正在跑的 DSH 去试**（那会真的把它弄挂）。这里用 mock 的 Cordis 上下文
 * 在**独立进程**里把插件跑起来，且分两次跑：
 *
 *   * 带 `unhandledRejection` 监听 → 数出发生了多少次（证明异常确实产生）；
 *   * **不带**监听（子进程）→ 看进程会不会真的退出、退出码是多少（证明后果）。
 *
 *     node tools/probe_plugin_bad_body.mjs
 *     node tools/probe_plugin_bad_body.mjs --child   （内部用，不带监听）
 */

import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN = path.join(HERE, '..', 'plugins', 'dsh-pet-bridge', 'lib', 'index.js');
const PORT = 8933;

const isChild = process.argv.includes('--child');

if (!isChild) {
  // ---------------- 父进程：先跑一个"不带监听"的子进程，看它会不会死 ----------
  console.log('');
  console.log('  验证：坏请求会不会带崩宿主进程（Node 默认行为）');
  console.log('  ' + '='.repeat(74));
  console.log('  插件: ' + path.relative(path.join(HERE, '..'), PLUGIN));

  const child = spawn(process.execPath, [fileURLToPath(import.meta.url), '--child'], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  let childOut = '';
  child.stdout.on('data', (chunk) => { childOut += chunk; });
  child.stderr.on('data', (chunk) => { childOut += chunk; });
  const exitCode = await new Promise((resolve) => child.on('exit', resolve));

  console.log('');
  console.log('  子进程退出码: ' + exitCode);
  for (const line of childOut.split('\n')) {
    if (line.trim()) console.log('    | ' + line.trim());
  }
  console.log('');
  if (exitCode !== 0) {
    console.log('  判定: [问题] 进程**非正常退出**（退出码 ' + exitCode + '）');
    console.log('        → unhandled rejection 会真的把宿主进程带走。');
  } else {
    console.log('  判定: [OK] 进程正常退出，没有因为坏请求而死。');
  }
  process.exit(exitCode !== 0 ? 1 : 0);
}

// ---------------- 子进程：**故意不注册 unhandledRejection 监听** ----------------
// 不注册时，Node 15+ 遇到 unhandled rejection 会打印错误并以非零码退出 —— 这正是
// DSH 宿主会经历的事。
const { apply } = await import('file://' + PLUGIN.replace(/\\/g, '/'));

const ctx = {
  on() {},
  logger: { warn: (...args) => console.log('[logger]', ...args) },
  llm: {
    async *stream() {
      yield { type: 'text-delta', index: 0, text: 'ok' };
      yield { type: 'finish', reason: 'stop' };
    },
  },
};
apply(ctx, { petPort: 59997, selfPort: PORT, whisperPrompt: '测试' });
await new Promise((resolve) => setTimeout(resolve, 400));

const post = (raw) => new Promise((resolve) => {
  const req = http.request(
    {
      host: '127.0.0.1', port: PORT, path: '/chat', method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(raw) },
    },
    (res) => {
      let text = '';
      res.on('data', (c) => { text += c; });
      res.on('end', () => resolve({ status: res.statusCode, text }));
    },
  );
  req.on('error', (error) => resolve({ status: -1, text: String(error) }));
  req.end(raw);
});

for (const [label, raw] of [
  ['JSON null', 'null'],
  ['JSON 数组', '[1,2]'],
  ['JSON 字符串', '"hello"'],
  ['JSON 数字', '42'],
]) {
  const resp = await post(raw);
  console.log(`${label}: 状态码 ${resp.status} ${String(resp.text).slice(0, 60)}`);
}

// 给 unhandled rejection 一点时间触发（如果会触发的话）
await new Promise((resolve) => setTimeout(resolve, 500));
console.log('子进程走到末尾都没退出 —— 说明这些坏 body 不会致命');
process.exit(0);
