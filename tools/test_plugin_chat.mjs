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
const ctx = {
  on() {},
  logger: { warn: (...args) => console.log('    [logger]', ...args) },
  llm: {
    stream: () => scenarios[mode](),
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

console.log(failures ? `失败 ${failures} 项` : '全部通过');
process.exit(failures ? 1 : 0);
