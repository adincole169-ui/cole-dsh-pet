// 被测插件的路径：默认从当前用户的家目录推出来，也可以用
// DSH_PLUGIN_DIR 环境变量覆盖（例：set DSH_PLUGIN_DIR=D:\somewhere）。
// 不要写死某个用户名——那是别人机器上的路径，测试在他那里必然失败。
import os from 'node:os';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const pluginDir = process.env.DSH_PLUGIN_DIR
  || path.join(os.homedir(), '.dsh', 'profiles', 'node_modules', 'dsh-pet-bridge');
const pluginEntry = path.join(pluginDir, 'lib', 'index.js');
const plugin = await import(pathToFileURL(pluginEntry).href);
const http = await import('node:http');
const PORT = 8917;
const results = [];
const check = (label, ok, detail='') => { console.log(`  ${ok?'OK  ':'FAIL'} ${label}${detail?'  '+detail:''}`); results.push(ok); };

let mode = 'ready';
let wallets = { value:[{currency:'CNY', balance:'37.20'}], bonusWallets:[{currency:'CNY', balance:'2.80'}] };
const ctx = {
  on(){}, logger:{ warn(){}, info(){} },
  llm: { stream: async function*(){ yield { type:'text-delta', index:0, text:'好' }; } },
  get(name){
    if (name !== 'deepseekAccount') return undefined;
    return { async getBalance(){
      if (mode === 'ready') return { status:'ready', ...wallets };
      if (mode === 'failed') return { status:'failed' };
      if (mode === 'throw') throw new Error('boom');
      return null;
    }};
  },
};
plugin.apply(ctx, { petPort: 8999, selfPort: PORT, balanceCacheSec: 0 });
await new Promise(r => setTimeout(r, 800));

const get = (path) => new Promise((resolve, reject) => {
  http.get({ host:'127.0.0.1', port:PORT, path }, (res) => {
    let b=''; res.on('data', c=>b+=c); res.on('end', ()=>resolve(JSON.parse(b)));
  }).on('error', reject);
});
const show = (h) => `tier=${h.usage.tier} total=${h.balance ? h.balance.total : 'null'}`;

mode='ready';
let h = await get('/health');
check('健康接口可用', h.ok === true);
check('主钱包 37.20 + 赠送 2.80 = 40', h.balance && Math.abs(h.balance.total - 40) < 1e-9, show(h));
check('40 元 -> 第 1 档 金袋叮当', h.usage.tier === 1, show(h));
check('币种 CNY', h.balance && h.balance.currency === 'CNY');

// 六档全覆盖（边界值与 config 的动画一一对应）
const bands = [[100,0,'钱袋满溢'],[30,1,'金袋叮当'],[12,2,'钱袋如常'],[6,3,'数金皱眉'],[3,4,'袋空如洗'],[0.5,5,'分文不剩']];
for (const [amount, want, label] of bands) {
  wallets = { value:[{currency:'CNY', balance:String(amount)}], bonusWallets:[] };
  h = await get('/health');
  check(`${amount} 元 -> 第 ${want} 档（${label}）`, h.usage.tier === want, show(h));
}

mode='failed';
h = await get('/health');
check('查询失败 -> balance=null，退回用量分档', h.balance === null, show(h));

mode='throw';
h = await get('/health');
check('抛异常不崩，返回 null', h.balance === null && h.ok === true, show(h));

mode='ready';
wallets = { value:[{currency:'USD', balance:'40'}], bonusWallets:[] };
h = await get('/health');
check('非 CNY 不猜汇率，退回用量分档', h.balance === null, show(h));

mode='ready';
ctx.get = () => undefined;   // 服务不存在
h = await get('/health');
check('服务不存在时也能返回（不崩）', h.ok === true, show(h));

console.log(results.every(Boolean) ? '全部通过' : `失败 ${results.filter(x=>!x).length} 项`);
process.exit(0);
