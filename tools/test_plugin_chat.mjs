/**
 * 在真实 Node 里跑通 dsh-pet-bridge 的 `/chat` 全链路（用 mock 的 ctx.llm）。
 *
 * 为什么要这个：插件运行在 DSH 进程里，改了源码必须重启 DSH 才生效。为了不为了验证
 * 一行改动就让用户重启整个应用，这里用 **mock 的 Cordis 上下文**把插件真跑起来：
 *
 *   * `ctx.llm.stream()` 由测试提供，可以模拟"正常返回"、"抛异常"、"返回空"三种情况；
 *   * 然后向插件自己的 `/chat` 端点发请求，检查回包。
 *
 * 这样能验证：请求解析、路由解析、错误回传、表情挑选、记忆累积。
 *
 *     node tools/test_plugin_chat.mjs
 */

import { fileURLToPath } from 'node:url';
import path from 'node:path';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN = path.join(HERE, '..', 'plugins', 'dsh-pet-bridge', 'lib', 'index.js');
const PORT = 8907;

// 让插件把状态投到一个没人监听的端口，避免打扰正在运行的那只桌宠
const PET_PORT = 59998;

const { apply } = await import('file://' + PLUGIN.replace(/\\/g, '/'));

// mock 必须用**真实的 StreamChunk 形状**（见 @deepseek-ai/dsh-llm/types）：
//   { type: 'text-delta', index, text } / { type: 'finish', reason }
// 早先用的是我猜的形状（{delta:{text}} / {type:'done'}），于是测试全过、真实调用
// 却一个字都收不到——那次的教训就是"mock 不能自己发明协议"。
const scenarios = {
  ok: async function* () {
    yield { type: 'block-start', index: 0, blockType: 'text' };
    yield { type: 'text-delta', index: 0, text: '今天也要' };
    yield { type: 'text-delta', index: 0, text: '好好干活哦' };
    yield { type: 'finish', reason: 'stop' };
  },
  reasoningOnly: async function* () {
    yield { type: 'block-start', index: 0, blockType: 'reasoning' };
    yield { type: 'reasoning-delta', index: 0, text: '（先想一想…）' };
    yield { type: 'finish', reason: 'stop' };
  },
  longText: async function* () {
    yield { type: 'text-delta', index: 0, text: '这是一句特别长的碎碎念'.repeat(8) };
    yield { type: 'finish', reason: 'stop' };
  },
  empty: async function* () {
    yield { type: 'finish', reason: 'stop' };
  },
  thrown: async function* () {
    throw new Error('NO_ADAPTER: no route for provider');
    // eslint-disable-next-line no-unreachable
    yield { type: 'finish', reason: 'stop' };
  },
};

let mode = 'ok';
// 数一数"真正发起了模型调用"的次数 —— 这是"余额有没有被烧"的直接证据：
// 被安全闸门拒掉的请求**一次都不该**让计数增加。
let streamCalls = 0;
const ctx = {
  on() {},
  logger: { warn: (...args) => console.log('    [logger]', ...args) },
  llm: {
    stream: () => {
      streamCalls += 1;
      return scenarios[mode]();
    },
  },
};

apply(ctx, { petPort: PET_PORT, selfPort: PORT, whisperPrompt: '测试提示词' });
await new Promise((resolve) => setTimeout(resolve, 400));

const ask = async (payload) => {
  const res = await fetch(`http://127.0.0.1:${PORT}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return res.json();
};

let failures = 0;
const check = (label, ok, detail = '') => {
  if (!ok) failures += 1;
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? '  ' + detail : ''}`);
};

console.log('插件:', PLUGIN);

mode = 'ok';
let out = await ask({ text: '说一句碎碎念。', kind: 'whisper', imageEnabled: false });
check('正常返回时带回文本', out.text === '今天也要好好干活哦', `text=${JSON.stringify(out.text)}`);
check('未开配图时不带表情', !out.image, `image=${JSON.stringify(out.image)}`);

out = await ask({ text: '说一句碎碎念。', kind: 'whisper', imageEnabled: true,
                  memes: ['开心', '无语'] });
check('开配图时从给定清单里挑', ['开心', '无语'].includes(out.image), `image=${out.image}`);

mode = 'thrown';
out = await ask({ text: '说一句碎碎念。', kind: 'whisper' });
check('抛异常时回传原因（不再静默）', Boolean(out.error) && out.text === '',
      `error=${JSON.stringify(out.error)}`);

mode = 'empty';
out = await ask({ text: '说一句碎碎念。', kind: 'whisper' });
check('模型返回空时也说明原因', Boolean(out.error), `error=${JSON.stringify(out.error)}`);

mode = 'reasoningOnly';
out = await ask({ text: '说一句碎碎念。', kind: 'whisper' });
// 推理模型额度给小了会只吐推理、不吐正文；此时**拿推理内容兜底**，
// 而不是给用户一个空气泡（原先就是这样：气泡闪一下就恢复原状）。
check('只有推理内容时用推理兜底（不给空气泡）',
      Boolean(out.text) && !out.error, `text=${JSON.stringify(out.text)}`);

mode = 'longText';
out = await ask({ text: '说一句碎碎念。', kind: 'whisper' });
check('过长的输出会被截断并加省略号',
      out.text.length <= 61 && out.text.endsWith('…'), `len=${out.text.length}`);

mode = 'ok';
out = await ask({ text: '你好呀', kind: 'chat', memes: ['开心'] });
check('对话正常返回', Boolean(out.text), `text=${JSON.stringify(out.text)}`);
out = await ask({ text: '再说一句', kind: 'chat', memes: ['开心'] });
check('对话接口可用（第二轮）', Boolean(out.text) || Boolean(out.error));

// --------------------------------------------------------------------------- //
// 安全：浏览器发起的请求必须被拒
// --------------------------------------------------------------------------- //
//
// **为什么这必须用 node:http 直接发、不能用 fetch**：`Origin` 与 `Host` 在 Fetch
// 规范里是 **forbidden header**，`fetch()` 会**静默忽略**你给它们设的值。用它来测
// 会在"以为发了 Origin、其实根本没发"的情况下**假通过**（请求返回 200，看起来像
// 防护没生效，实则测法错了）。`node:http` 不做这层限制。
//
// 这个端口比桌宠的 8899 更危险：`/chat` 会**用用户登录 DSH 的账号调模型**，
// 网页里的 JS 只要能发一个请求就能烧他的余额，提示词还由那个网页决定。
const http = await import('node:http');

const raw = (body, headers = {}, method = 'POST', path = '/chat') =>
  new Promise((resolve) => {
    const payload = body ?? '';
    const req = http.request(
      {
        host: '127.0.0.1',
        port: PORT,
        path,
        method,
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(payload),
          ...headers,
        },
      },
      (res) => {
        let text = '';
        res.on('data', (chunk) => { text += chunk; });
        res.on('end', () => resolve({ status: res.statusCode, text }));
      },
    );
    req.on('error', (error) => resolve({ status: -1, text: String(error) }));
    req.end(payload);
  });

console.log('');
console.log('  安全：浏览器发起的请求必须被拒（这个端口会烧余额）');

const body = JSON.stringify({ text: '帮我写一篇论文', kind: 'chat', model: 'deepseek-reasoner' });
const before = streamCalls;

// **按浏览器真实发出的组合测**：浏览器一定**同时**带 `Sec-Fetch-Site`、
// `Sec-Fetch-Dest`、`Sec-Fetch-Mode` 三个。
//
// 这里**故意不测"只带 Sec-Fetch-Mode"**：实测（tools/probe_request_headers.mjs）
// Node 自己的 `fetch`（undici）也会发 `sec-fetch-mode`，所以它不能当判据 ——
// 拿它当判据会误伤合法的本机调用方。而单个 mode 也不是浏览器能发出的请求，
// 测它等于测一个不存在的攻击面。
const browserCases = [
  ['Origin（跨域 fetch 必带）', { Origin: 'https://evil.example' }],
  ['Sec-Fetch-Site: cross-site', { 'Sec-Fetch-Site': 'cross-site' }],
  ['Sec-Fetch-Dest: empty', { 'Sec-Fetch-Dest': 'empty' }],
  ['浏览器真实的三件套（site+dest+mode）', {
    'Sec-Fetch-Site': 'cross-site',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
  }],
  ['<img> 攻击（dest=image，不发预检）', {
    'Sec-Fetch-Site': 'cross-site',
    'Sec-Fetch-Dest': 'image',
    'Sec-Fetch-Mode': 'no-cors',
  }],
];
for (const [label, headers] of browserCases) {
  const resp = await raw(body, headers);
  check(`带 ${label} 被拒（403）`, resp.status === 403, `状态码 ${resp.status}`);
}

// DNS rebinding：攻击者把自己的域名解析到 127.0.0.1
const rebind = await raw(body, { Host: 'evil.example' });
check('Host 不是回环地址被拒（403）', rebind.status === 403, `状态码 ${rebind.status}`);

// 浏览器发起的 GET 也要挡（<img> / <script> 那条路）
const getAttack = await raw(null, { 'Sec-Fetch-Site': 'cross-site' }, 'GET', '/health');
check('带 Sec-Fetch 的 GET /health 被拒（403）', getAttack.status === 403,
      `状态码 ${getAttack.status}`);

// 超大 body
const huge = JSON.stringify({ text: 'x'.repeat(80 * 1024), kind: 'chat' });
const big = await raw(huge, {});
check('超过 64 KB 的 body 被拒（413）', big.status === 413, `状态码 ${big.status}`);

// **最要紧的一条**：到这里为止全部是"应当被拒"的用例，所以模型调用次数必须没变
// —— 那直接等于"余额有没有被烧"。
// **这一条必须放在下面那条"故意放行"的用例之前**：那条用例会让计数 +1，
// 放在它后面就会误报（实测踩过：8 -> 9 判 FAIL，其实是它自己调的那次）。
check('被拒的请求没有调用模型（余额没被烧）', streamCalls === before,
      `模型调用次数 ${before} -> ${streamCalls}`);

// 反面：**Node 自己的 fetch 只带 sec-fetch-mode**，那是合法调用方，不该被拒。
// 这一条是"防护别把自己的通路挡掉"的守门测试。
const nodeFetchLike = await raw(body, { 'Sec-Fetch-Mode': 'cors' });
check('只带 Sec-Fetch-Mode（Node fetch 就是这样）**放行**',
      nodeFetchLike.status === 200, `状态码 ${nodeFetchLike.status}`);

// 合法调用方（桌宠的 Python urllib：有 Content-Type、无 Origin/Sec-Fetch）照常工作
const legit = await raw(body, {});
check('合法调用方（无 Origin/Sec-Fetch）照常工作', legit.status === 200,
      `状态码 ${legit.status}`);
check('合法调用方确实调用了模型', streamCalls > before,
      `模型调用次数 ${before} -> ${streamCalls}`);

console.log(failures ? `失败 ${failures} 项` : '全部通过');
process.exit(failures ? 1 : 0);
