/**
 * 实测：各种"合法调用方"到底会发哪些头。
 *
 * 为什么必须测：给本机服务加"挡住浏览器请求"的闸门时，判据是
 * "**请求带不带 Origin / Sec-Fetch-***"。我在注释里断言过"Node 的 fetch 不带" ——
 * 结果一跑测试就大面积失败，说明那个断言是错的。
 *
 * 这个脚本起一个本地服务，把每种客户端真实发出的头原样打出来。
 *
 *     node tools/probe_request_headers.mjs
 */

import http from 'node:http';

const PORT = 8931;
const seen = [];

const server = http.createServer((req, res) => {
  seen.push({ from: req.headers['x-probe-client'] || '?', headers: { ...req.headers } });
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end('{"ok":true}');
});
await new Promise((r) => server.listen(PORT, '127.0.0.1', r));

const URL_ = `http://127.0.0.1:${PORT}/chat`;

// 1) Node 的 fetch（tools/*.mjs 自检用的就是它）
await fetch(URL_, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json', 'x-probe-client': 'node-fetch' },
  body: JSON.stringify({ text: 'hi' }),
});

// 2) Node 的 http.request（插件投状态用的就是它）
await new Promise((resolve) => {
  const body = JSON.stringify({ text: 'hi' });
  const req = http.request(
    {
      host: '127.0.0.1', port: PORT, path: '/chat', method: 'POST',
      headers: {
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Length': Buffer.byteLength(body),
        'x-probe-client': 'node-http',
      },
    },
    (res) => { res.resume(); res.on('end', resolve); },
  );
  req.end(body);
});

// 3) 模拟浏览器：跨域 POST 会带 Origin（含 Sec-Fetch-*）
await fetch(URL_, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Origin: 'https://evil.example',
    'x-probe-client': 'browser-like(Origin)',
  },
  body: JSON.stringify({ text: 'hi' }),
});

// 4) 直接看 fetch 能不能设 Origin（Fetch 规范里它是 forbidden header）
await fetch(URL_, {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    Origin: 'https://forbidden-test.example',
    'Sec-Fetch-Site': 'cross-site',
    Host: 'forbidden-host.example',
    'x-probe-client': 'set-forbidden-headers',
  },
  body: JSON.stringify({ text: 'hi' }),
});

server.close();

console.log('');
console.log('  各客户端真实发出的请求头');
console.log('  ' + '='.repeat(74));
for (const item of seen) {
  const interesting = Object.keys(item.headers)
    .filter((k) => k.startsWith('sec-') || k === 'origin' || k === 'host'
      || k.startsWith('x-probe') || k === 'content-type')
    .sort();
  const shown = {};
  for (const k of interesting) shown[k] = item.headers[k];
  const flag = (shown.origin || Object.keys(shown).some((k) => k.startsWith('sec-')))
    ? '  <- 会被闸门拒掉'
    : '  <- 放行';
  console.log(`  ${item.from.padEnd(28)} ${JSON.stringify(shown)}${flag}`);
}

console.log('');
console.log('  判读');
console.log('  ' + '='.repeat(74));
const nodeFetch = seen.find((s) => s.from === 'node-fetch');
const nodeHttp = seen.find((s) => s.from === 'node-http');
const forbidden = seen.find((s) => s.from === 'set-forbidden-headers');
const report = (label, item) => {
  if (!item) { console.log(`  ${label}: 没抓到`); return; }
  const keys = Object.keys(item.headers);
  const hasOrigin = keys.includes('origin');
  const secKeys = keys.filter((k) => k.startsWith('sec-'));
  console.log(`  ${label}: Origin=${hasOrigin}  Sec-Fetch-*=${secKeys.length ? secKeys.join(',') : '无'}`);
};
report('node fetch      ', nodeFetch);
report('node http.request', nodeHttp);
report('显式设 forbidden  ', forbidden);
console.log('');
console.log('  结论要点：');
console.log('    * 如果 node fetch 带了 sec-fetch-*，那么"只按 Sec-Fetch 判浏览器"会误伤自检；');
console.log('    * 如果显式设 Origin/Host 真的没生效，说明 fetch 忽略 forbidden header，');
console.log('      那么用 fetch 测安全闸门会**假通过**，必须改用 node:http。');
