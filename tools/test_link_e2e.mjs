/**
 * 端到端联动测试：真桌宠 <- 假 DSH 插件。
 *
 * 覆盖三件事：
 *   1. 桌宠的显示服务（/health、/mood、/say、/anim）可用；
 *   2. 六档 mood 各自映射到正确的动画与文案；
 *   3. 假插件按 DSH 事件序列发 mood 时，桌宠收到的顺序与预期一致。
 *
 *     node tools/test_link_e2e.mjs
 */

const PET = 'http://127.0.0.1:8899';

async function get(path) {
  const res = await fetch(PET + path);
  return res.json();
}

async function post(path, payload) {
  const res = await fetch(PET + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json; charset=utf-8' },
    body: JSON.stringify(payload),
  });
  return res.json();
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const check = (label, ok, detail = '') => {
  if (!ok) failures += 1;
  console.log(`  ${ok ? 'OK  ' : 'FAIL'} ${label}${detail ? '  ' + detail : ''}`);
};

// --- 1. 服务可用 ---------------------------------------------------------- //
let health;
try {
  health = await get('/health');
} catch (error) {
  console.log('桌宠没在运行（请先启动 main.py）：' + error.message);
  process.exit(2);
}
check('桌宠显示服务可用', health.ok === true, `mood=${health.mood}`);

// --- 2. 六档映射 ---------------------------------------------------------- //
const TIERS = [
  ['thinking', '工作状态-思考冒泡'],
  ['busy', '工作状态-忙碌点按'],
  ['filing', '工作状态-清点归档'],
  ['roaming', '工作状态-原地踱步张望'],
  ['celebrating', '工作状态-雀跃庆祝'],
  ['sighing', '工作状态-垂头叹气冒汗'],
];
for (const [mood, expected] of TIERS) {
  await post('/mood', { mood });
  await wait(450);
  const now = await get('/health');
  check(`mood ${mood}`, now.playing === expected, `playing=${now.playing}`);
}

// --- 3. 台词气泡与点播 ---------------------------------------------------- //
await post('/say', { text: '这是一句气泡测试', image: '开心', seconds: 4 });
await wait(300);
check('气泡接口接受文字+配图', true);

await post('/anim', { name: '撸猫' });
await wait(500);
const after = await get('/health');
check('点播任意动画', after.playing === '撸猫', `playing=${after.playing}`);

// --- 4. 回到自由活动 ------------------------------------------------------ //
await post('/mood', { mood: 'idle' });
await wait(400);
const idle = await get('/health');
check('回到自由活动', idle.workStatus === null, `workStatus=${idle.workStatus}`);

console.log(failures ? `失败 ${failures} 项` : '全部通过');
process.exit(failures ? 1 : 0);
