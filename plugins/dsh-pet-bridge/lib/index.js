/**
 * Host half of `dsh-pet-bridge`: mirror DSH session state onto the desktop pet,
 * and answer the pet's model requests (碎碎念 / 对话).
 *
 * Two directions, two servers — deliberately:
 *
 *   pet  :8899   <- this plugin POSTs mood / say      (state mirroring)
 *   this :8900   <- the pet POSTs chat, GETs health   (model access)
 *
 * The split exists because of what each side owns. The pet owns its own display
 * service and must keep working with no plugin installed, so the plugin is only
 * ever a *sender* there. The model, on the other hand, only exists inside DSH, so
 * the pet has to call out to reach it. Keeping both on loopback means neither
 * side needs a public port and the pet degrades gracefully on its own.
 *
 * Mood mapping (six tiers, matching `events.workStatus` in the pet's config):
 *
 *   thinking     an agent turn just started
 *   busy         a tool call is in flight
 *   filing       several tool calls finished, the agent is still going
 *   roaming      waiting on the user
 *   celebrating  a turn ended without error
 *   sighing      the agent reported an error
 *
 * `approval/asked` deliberately maps to `thinking`: the pet's tier 0 text is the
 * "I need you to confirm" group, so the animation and the wording line up.
 *
 * @module dsh-pet-bridge
 */

/** Stable Cordis plugin name. */
export const name = 'dsh-pet-bridge';

/**
 * 服务依赖声明。
 *
 * **必须声明 `llm`**：Cordis 只把插件声明过的服务挂到它的上下文上，没声明时
 * `ctx.llm` 会直接抛 `Error: cannot get property "llm" without inject`。
 * 这正是碎碎念/对话"点了没反应"的根因——插件压根没拿到模型服务。
 */
// 触发重载标记: 1791105701
export const inject = ['llm', 'deepseekAccount'];

/** Where the pet's display service listens. */
const DEFAULT_PET_PORT = 8899;

/** Where this plugin's model service listens (the pet calls it). */
const DEFAULT_SELF_PORT = 8900;

/** 请求体上限（字节）。桌宠问一句远用不到 64 KB；不设上限的话一个巨大的 body
 *  就能把插件（宿主进程的一部分）的内存吃满。 */
const MAX_BODY_BYTES = 64 * 1024;

/** How long a tool call may stay silent before "busy" decays to "filing". */
const BUSY_DECAY_MS = 4000;

/** How long a one-shot mood (celebrating / sighing) holds before going idle. */
const FLASH_MS = 6000;

/** Sticker names the pet ships in `memes/`; the model picks one or none. */
const MEMES = [
  ['开心', '开心地笑'],
  ['无语', '无语、无奈'],
  ['震惊', '震惊、惊讶'],
  ['加油', '打气、鼓励'],
  ['哭', '委屈、难过'],
  ['得意', '得意、骄傲'],
  ['生气', '生气、不满'],
  ['问号', '疑惑、不解'],
];

/**
 * 可用的表情清单。**以桌宠传来的为准**（它读 `memes/` 目录，对得上实际文件），
 * 插件内置的清单只在桌宠没传时兜底。
 */
const memePool = (names) => {
  if (!Array.isArray(names) || !names.length) return MEMES;
  return names.map((name) => {
    const known = MEMES.find(([key]) => key === name);
    return known || [String(name), String(name)];
  });
};

/**
 * 截断过长的输出。
 *
 * 桌宠的气泡只能显示一两行，而推理模型的输出可能很长；同时 `clip` 也顺手去掉
 * 换行，避免气泡里出现奇怪的折行。
 */
const clip = (value, limit) => {
  const flat = String(value || '').replace(/\s+/g, ' ').trim();
  if (flat.length <= limit) return flat;
  return flat.slice(0, limit).replace(/[，。、；：,.;:!！?？]+$/, '') + '…';
};

/**
 * Mirror session state to the pet, and serve the pet's model requests.
 *
 * 碎碎念的**周期不在这里**：只有桌宠读得到 `whisperEnabled` 与
 * `eventsRefreshSec.whisper`，所以由它按周期发 `kind=whisper` 请求，本插件只负责
 * 生成那一名话。
 *
 * @param ctx - Host plugin context.
 * @param config - `{ petPort, selfPort, provider, model, whisperPrompt, memoryRounds }`.
 */
export function apply(ctx, config = {}) {
  const petPort = Number(config.petPort) || DEFAULT_PET_PORT;
  const selfPort = Number(config.selfPort) || DEFAULT_SELF_PORT;
  // 留空 = 跟随当前对话的模型（与 dsh-pet 的语义一致）
  const wantProvider = typeof config.provider === 'string' ? config.provider : '';
  const wantModel = typeof config.model === 'string' ? config.model : '';
  const whisperPrompt = typeof config.whisperPrompt === 'string' && config.whisperPrompt
    ? config.whisperPrompt
    : '你是主人桌面上的Q版蓝发小女仆，会时不时碎碎念一句。说话要自然随意、短短一句（20字以内），'
      + '温柔乖巧带点俏皮，说人话不唠叨，不要解释你自己，不要提你是AI。';

  let busyTimer = null;
  let flashTimer = null;
  let toolsThisTurn = 0;
  // 用量累计：当前 DSH 没有余额接口，所以用真实可得的会话用量分档。
  let totalTurns = 0;
  let totalSteps = 0;
  let sessionTokens = 0;
  // 对话记忆：内存里保留最近若干轮（1 轮 = 1 问 1 答）
  const memory = [];
  const memoryRounds = Number(config.memoryRounds) || 5;

  // `busyWatchdog` 的声明在下面（`scheduleBusyWatchdog` 附近）；这里用函数声明
  // 而不是 const 箭头函数，避免"先引用后定义"。
  function cancelBusyWatchdog() {
    if (busyWatchdog) {
      clearTimeout(busyWatchdog);
      busyWatchdog = null;
    }
  }

  const clearBusy = () => {
    if (busyTimer) {
      clearTimeout(busyTimer);
      busyTimer = null;
    }
    // 有真实活动（工具返回 / 新一轮开始 / 一次性状态）就撤掉兜底看门狗，
    // 否则它会在正常工作途中把宠物拨回 idle。
    cancelBusyWatchdog();
  };

  /** Resolve the provider/model to call: explicit config first, else the default agent route. */
  const resolveRoute = () => {
    if (wantProvider && wantModel) return { provider: wantProvider, model: wantModel };
    try {
      const picked = ctx.get?.('agent-default-model');
      const value = typeof picked === 'function' ? picked() : picked;
      if (value && value.provider && value.model) return { provider: value.provider, model: value.model };
    } catch {
      /* 取不到就退回下面的硬编码默认 */
    }
    return { provider: 'deepseek-account', model: 'deepseek-flash' };
  };

  /**
   * One-shot model call.
   *
   * 失败时**把原因回传**而不是静默返回空串：原先只写进 DSH 的 logger，而那一侧我
   * 看不到，于是桌宠只收到一个空字符串，无从判断是"模型没说话"还是"调用报错"。
   * 现在返回 `{ text, error }`，错误会一路冒泡到桌宠的气泡上。
   */
  const askDetailed = async (system, userText, maxTokens = 800, options = {}) => {
    // 桌宠可以在请求里指定 provider/model（对应 config.jsonc 的 whisperModel /
    // chatModel）；留给空就跟随当前对话的模型。
    let provider = options.provider;
    let model = options.model;
    if (!provider || !model) {
      const route = resolveRoute();
      provider = provider || route.provider;
      model = model || route.model;
    }
    const request = {
      provider,
      model,
      system,
      messages: [{ role: 'user', content: [{ type: 'text', text: userText }] }],
      maxTokens,
      temperature: 1.0,
      purpose: 'compaction',
    };
    let text = '';
    let reasoning = '';
    try {
      for await (const chunk of ctx.llm.stream(request)) {
        // 真实的 StreamChunk 形状（见 @deepseek-ai/dsh-llm 的 types）：
        //   { type: 'text-delta',      index, text }
        //   { type: 'reasoning-delta', index, text }
        //   { type: 'finish', reason }
        // 原先按 `chunk.delta.text` / `chunk.text` / `chunk.delta.content[0].text`
        // 去取，一个都对不上，于是"不抛异常但文本始终为空"——桌宠那边表现为
        // 点了碎碎念完全没反应。
        const type = chunk?.type;
        if (type === 'text-delta') {
          if (typeof chunk.text === 'string') text += chunk.text;
        } else if (type === 'reasoning-delta') {
          // 推理内容不算回答；只在没有正文时兜底，避免把思考过程当台词
          if (typeof chunk.text === 'string') reasoning += chunk.text;
        } else if (type === 'finish') {
          break;
        }
      }
    } catch (error) {
      const reason = `${error?.name || 'Error'}: ${error?.message ?? error}`;
      ctx.logger?.warn?.('dsh-pet-bridge: 模型调用失败 ' + reason);
      return { text: '', error: reason, provider, model };
    }
    if (!text.trim() && reasoning.trim()) {
      // 推理模型（deepseek-flash 等）会先吐 reasoning-delta。额度给小了，推理就把
      // 额度吃光、正文一个字都剩不下——这正是"碎碎念只闪一下就恢复原状"的原因：
      // 气泡先显示占位符，回调却拿到空文本。
      // 这种情况**拿推理内容兜底**，而不是给用户一个空气泡。
      return { text: clip(reasoning, 40), error: '', provider, model, usedReasoning: true };
    }
    if (!text.trim()) {
      return { text: '', error: `模型返回空内容（provider=${provider} model=${model}）`,
               provider, model };
    }
    return { text: clip(text, 60), error: '', provider, model };
  };

  /** 兼容旧调用点：只要文本。 */
  const ask = async (system, userText, maxTokens = 200, options = {}) =>
    (await askDetailed(system, userText, maxTokens, options)).text;

  /** POST to the pet. Failures are expected whenever the pet is not running. */
  const send = (path, payload) => {
    const body = JSON.stringify(payload);
    import('node:http')
      .then(({ request }) => {
        const req = request(
          {
            host: '127.0.0.1',
            port: petPort,
            path,
            method: 'POST',
            headers: {
              'Content-Type': 'application/json; charset=utf-8',
              'Content-Length': Buffer.byteLength(body),
            },
          },
          (res) => res.resume(),
        );
        req.on('error', () => {});
        req.setTimeout(1500, () => req.destroy());
        req.end(body);
      })
      .catch(() => {});
  };

  const sendMood = (mood, text = '') => send('/mood', { mood, text });
  const sendSay = (text, image = '', seconds = 6) => send('/say', { text, image, seconds });
  const sendUsage = (tier, text) => send('/usage', { tier, text });

  /**
   * 账户余额（DSH `deepseekAccount.getBalance`）。
   *
   * 这是 0.2.0 才有的服务——当初写这段时 DSH 是 0.1.0-rc.7，**没有任何余额 API**，
   * 所以只能退回"轮次 + 步数"分档。用户升级到 0.2.0-rc.2 后这里才真正可用。
   *
   * 返回体（`AccountDetails['balance']`）：
   *   { status:'ready', value: readonly {currency,balance}[], bonusWallets: [...] }
   *   | { status:'failed' }
   * `balance` 是**字符串**（可能是 "12.34"），要自己转数字。
   * 未登录或授权变更时返回 null。
   */
  // 缓存时长可配置：默认 60 秒。做成配置项有两个用处——用户能调刷新频率，
  // 测试能用极短的值验证"多条分支"（否则第二次查询会命中缓存，测不到变化）。
  const BALANCE_TTL_MS = Math.max(0, Number(config?.balanceCacheSec ?? 60)) * 1000;
  let balanceCache = { at: 0, value: undefined };
  let balanceInflight = null;

  const clientMetadata = () => ({
    version: '0.0.0',
    locale: (typeof Intl !== 'undefined' && Intl.DateTimeFormat().resolvedOptions().locale) || 'zh-CN',
    timezoneOffsetSeconds: -new Date().getTimezoneOffset() * 60,
  });

  /** 取余额（带缓存）。失败返回 undefined，调用方据此退回用量分档。 */
  const fetchBalance = async () => {
    const now = Date.now();
    if (balanceCache.value !== undefined && now - balanceCache.at < BALANCE_TTL_MS) {
      return balanceCache.value;
    }
    if (balanceInflight) return balanceInflight;
    balanceInflight = (async () => {
      let result;
      try {
        const account = ctx.get('deepseekAccount');
        if (!account || typeof account.getBalance !== 'function') {
          result = undefined;                       // 服务不在：静默退回用量分档
        } else {
          const details = await account.getBalance(clientMetadata());
          if (!details || details.status !== 'ready') {
            result = undefined;                     // 未登录 / 查询失败
          } else {
            const wallets = [
              ...(details.value || []),
              ...(details.bonusWallets || []),
            ];
            const total = wallets.reduce(
              (sum, wallet) => sum + (Number.parseFloat(wallet?.balance) || 0), 0);
            const currency = (wallets[0] && wallets[0].currency) || 'CNY';
            // 非人民币时**不猜汇率**：档位阈值是按人民币定的，硬套到美元上会把
            // "$40" 判成"分文不剩"。这种情况当作取不到余额，退回用量分档。
            result = currency === 'CNY' ? { total, currency, wallets } : undefined;
          }
        }
      } catch (error) {
        ctx.logger?.warn?.('dsh-pet-bridge: 取余额失败 ' + (error?.message ?? error));
        result = undefined;
      }
      balanceCache = { at: Date.now(), value: result };
      balanceInflight = null;
      return result;
    })();
    return balanceInflight;
  };

  /**
   * 余额 → 六档，**与 `config.jsonc` 的 `events.balance` 一一对应**：
   *
   *   0 余额-钱袋满溢   > 50 元        3 余额-数金皱眉  5 ~ 10 元
   *   1 余额-金袋叮当   20 ~ 50 元     4 余额-袋空如洗  2 ~ 5 元
   *   2 余额-钱袋如常   10 ~ 20 元     5 余额-分文不剩  < 2 元
   *
   * 写成显式区间（而不是一串"低于它就匹配"的规则）是有意的：先前用后者时边界很容易
   * 错位，实测出过"40 元被判成最低档"。区间一目了然，也能直接对着上表核对。
   */
  const BALANCE_BANDS = [
    { min: 50, label: '余额充足' },
    { min: 20, label: '还够用' },
    { min: 10, label: '用掉一半了' },
    { min: 5, label: '不多了' },
    { min: 2, label: '快见底了' },
    { min: 0, label: '分文不剩' },
  ];

  const balanceTier = (total) => {
    const amount = Number(total);
    if (!Number.isFinite(amount)) return BALANCE_BANDS.length - 1;
    for (let index = 0; index < BALANCE_BANDS.length; index += 1) {
      if (amount >= BALANCE_BANDS[index].min) return index;
    }
    return BALANCE_BANDS.length - 1;
  };
  const balanceTierLabel = (total) => BALANCE_BANDS[balanceTier(total)].label;
  // 导出给测试直接调用。先前用"抠源码再 eval"的方式测过，被 `const` 提升坑了
  // （替换成 var 后 BALANCE_TIERS 在赋值前是 undefined），得出过误导性的结论——
  // 所以宁可多暴露一个纯函数，也不要在测试里复刻实现。
  //
  // **注意**：这里的本地 `const balanceTierLabel` 不能省。我一度把它删掉、只留
  // `apply.balanceTierLabel = ...`，而 `reportUsage` 用的仍是本地名字，于是运行时
  // `ReferenceError: balanceTierLabel is not defined`——那个异常在 setTimeout 回调里
  // 抛出，直接把**整个 DSH host 进程**带崩了（见下一节"插件绝不能拖垮宿主"）。
  apply.balanceTier = balanceTier;
  apply.balanceTierLabel = balanceTierLabel;

  /**
   * 会话用量 → 六档（**余额拿不到时的回退**）。
   *
   * 硬编一个金额就是假数据，所以余额不可用时用**真实可得**的用量指标：轮次与工具步数。
   * 档位数量、动画、气泡位置都与余额分档一致，只有"输入量"换了来源。
   */
  const TIERS = [
    { max: 0, label: '还没什么用量' },
    { max: 3, label: '刚起步' },
    { max: 8, label: '用了一些' },
    { max: 20, label: '用得不少' },
    { max: 45, label: '用得很凶' },
    { max: Infinity, label: '火力全开' },
  ];

  const pickTier = () => {
    // 轮次是主指标，步数作为细粒度补充，避免"一轮里跑了很多步"看不出差别
    const score = totalTurns + totalSteps / 4;
    for (let index = 0; index < TIERS.length; index += 1) {
      if (score <= TIERS[index].max) return index;
    }
    return TIERS.length - 1;
  };

  const reportUsage = async () => {
    // 优先用真实余额；取不到才退回会话用量
    const balance = await fetchBalance();
    if (balance) {
      sendUsage(balanceTier(balance.total),
                `余额 ${balance.total.toFixed(2)} ${balance.currency}｜${balanceTierLabel(balance.total)}`);
      return;
    }
    const tier = pickTier();
    sendUsage(tier, `${TIERS[tier].label}｜${totalTurns} 轮 · ${totalSteps} 步`);
  };

  /**
   * 把回调包一层：**插件自己的异常绝不允许拖垮 DSH 宿主**。
   *
   * 血泪教训：一次重构里我漏了个局部函数，`reportUsage` 在 `setTimeout` 回调里抛
   * `ReferenceError: balanceTierLabel is not defined`，而 DSH 的宿主进程直接
   * `fatal load failure: exited with 1` —— **整个应用崩了**，不只是桌宠掉线。
   * 一个装饰性插件不该有这个能力。所以事件处理器与所有定时器回调都过这一层：
   * 出错只记一行 warn，互不牵连。
   */
  const guard = (label, fn) => (...args) => {
    try {
      return fn(...args);
    } catch (error) {
      try {
        ctx.logger?.warn?.(`dsh-pet-bridge: ${label} 出错（已忽略）: ${error?.message ?? error}`);
      } catch {
        /* 连日志都失败就只能放弃 */
      }
      return undefined;
    }
  };

  /** 带保护的 `ctx.on`：所有事件订阅都走它。 */
  const safeOn = (event, handler) => ctx.on(event, guard(event, handler));

  /**
   * busy 状态的兜底看门狗。
   *
   * 为什么需要它：`sendMood('busy')` 之后，能把它清掉的只有 `tools/result` 的 4 秒
   * 衰减、或 `agent/status idle`。而后者依赖 DSH 在**这一轮结束时**确实派发了状态
   * 事件；一旦一轮以错误/中断结尾、或事件被漏掉，宠物就会永久卡在同一个工作动作上
   * （用户报"停下来只有一个动作"，实测 `workStatus` 一直不回 None）。
   *
   * 阈值取得比单次工具耗时长得多：只是防止**永久**卡住，不打断正常的长任务。
   */
  const BUSY_WATCHDOG_MS = Math.max(0, Number(config?.busyWatchdogSec ?? 90)) * 1000;
  let busyWatchdog = null;

  const scheduleBusyWatchdog = () => {
    if (busyWatchdog) clearTimeout(busyWatchdog);
    busyWatchdog = setTimeout(guard('busy 看门狗', () => {
      busyWatchdog = null;
      busyTimer = null;
      sendMood('idle');
    }), BUSY_WATCHDOG_MS);
  };

  /** One-shot states fall back to idle (自由活动) after a moment. */
  const flash = (mood) => {
    sendMood(mood);
    if (flashTimer) clearTimeout(flashTimer);
    flashTimer = setTimeout(guard('一次性状态回落', () => {
      flashTimer = null;
      sendMood('idle');
    }), FLASH_MS);
  };

  // ------------------------------------------------------------ 碎碎念/对话 --
  // 碎碎念**没有**插件侧定时器：周期由桌宠驱动（它才读得到 `whisperEnabled` 与
  // `eventsRefreshSec.whisper`）。插件只在收到 `kind=whisper` 的请求时生成一句话，
  // 否则用户在配置里关掉碎碎念也照样会被推。
  const startServer = () => {
    import('node:http')
      .then(({ createServer }) => {
        const server = createServer((req, res) => {
          const reply = (code, payload) => {
            const body = JSON.stringify(payload);
            res.writeHead(code, {
              'Content-Type': 'application/json; charset=utf-8',
              // 不让浏览器猜类型：万一有人用 <script src> 指过来，
              // nosniff 能让它不去把 JSON 当脚本执行。
              'X-Content-Type-Options': 'nosniff',
            });
            res.end(body);
          };

          // ---- 安全闸门 -------------------------------------------------- //
          //
          // **这个端口比桌宠的 8899 更危险**：`/chat` 会**用用户登录 DSH 的账号
          // 调用模型** —— 网页里的 JS 只要能发一个请求，就能烧他的余额，
          // 而且提示词完全由那个网页决定。
          //
          // 只绑回环地址挡不住浏览器：任何网页（钓鱼站、被植入的广告、论坛 XSS）
          // 都能 `fetch('http://127.0.0.1:8900/chat', ...)`。
          //
          // **加 CORS 头没用**：攻击者不需要读响应，只要请求被执行就够；而且跨域
          // POST 常被浏览器当成"简单请求"，**不发预检**，请求直接就出去了。
          // 也不能靠检查 Content-Type —— 简单请求的 Content-Type 会被降级成 text/plain。
          //
          // 判据是"**这个请求是不是浏览器发起的**"。实测
          // （tools/probe_request_headers.mjs）各客户端真实发出的头：
          //
          //   node:http.request（桌宠投状态……不，是插件投状态）  Origin=无  Sec-Fetch-*=无
          //   Python urllib（桌宠问本插件）                      Origin=无  Sec-Fetch-*=无
          //   Node fetch（自检用）                              Origin=无  Sec-Fetch-*=**sec-fetch-mode**
          //   浏览器（跨域 fetch / <img> / 表单）                 Origin=有  Sec-Fetch-*=site,dest,mode
          //
          // 所以**只看 `Origin` / `Sec-Fetch-Site` / `Sec-Fetch-Dest`，不看 `Sec-Fetch-Mode`**：
          // `sec-fetch-mode` 是唯一连 Node 的 fetch（undici）也会发的，拿它当判据会误伤
          // 合法的本机调用方；而浏览器**必定同时带 site 与 dest**，排除 mode 不损失覆盖。
          const BROWSER_HEADERS = ['origin', 'sec-fetch-site', 'sec-fetch-dest'];
          const reqHeaders = req.headers || {};
          const fromBrowser = Object.keys(reqHeaders).some(
            (key) => BROWSER_HEADERS.includes(key.toLowerCase()),
          );
          const hostName = String(reqHeaders.host || '')
            .split(':')[0]
            .replace(/^\[|\]$/g, '')
            .toLowerCase();
          // Host 必须是回环地址 —— 挡 DNS rebinding（攻击者把域名解析到 127.0.0.1）。
          const hostOk = ['', '127.0.0.1', 'localhost', '::1'].includes(hostName);
          if (fromBrowser || !hostOk) {
            // 用模板字符串而不是 `%s` 占位符：占位符要靠 logger 自己格式化，
            // 不保证所有实现都做（自检里的 logger 就不做，于是日志里是字面 `%s`）。
            ctx.logger?.warn?.(
              `dsh-pet-bridge: 拒绝了一个${fromBrowser ? '浏览器发起' : 'Host 非回环地址'}`
              + `的请求 ${req.url || ''} —— 可能有网页在尝试用你的账号调用模型`,
            );
            reply(403, { ok: false, error: 'forbidden' });
            return;
          }

          if (req.method === 'GET' && req.url?.startsWith('/health')) {
            // `balance` 是给诊断用的：把真实余额原样暴露出来，才能核对分档阈值对不对
            // （`null` = 没登录或查询失败，此时桌宠走用量分档）。
            // 注意这个回调**必须**声明成 async 才能 await（写成同步回调会直接
            // 语法错误：`Unexpected reserved word`）。
            fetchBalance().then((balance) => {
              reply(200, {
                ok: true,
                memory: memory.length,
                model: resolveRoute(),
                usage: {
                  turns: totalTurns,
                  steps: totalSteps,
                  tokens: sessionTokens,
                  tier: balance ? balanceTier(balance.total) : pickTier(),
                },
                balance: balance
                  ? {
                      total: balance.total,
                      currency: balance.currency,
                      wallets: balance.wallets,
                    }
                  : null,
              });
            }).catch(() => {
              reply(200, {
                ok: true,
                memory: memory.length,
                model: resolveRoute(),
                usage: { turns: totalTurns, steps: totalSteps, tokens: sessionTokens, tier: pickTier() },
                balance: null,
              });
            });
            return;
          }

          if (req.method !== 'POST' || !req.url?.startsWith('/chat')) {
            reply(404, { ok: false });
            return;
          }

          let body = '';
          let bodyTooBig = false;
          req.on('data', (chunk) => {
            if (bodyTooBig) {
              return;
            }
            body += chunk;
            // 上限 64 KB：桌宠问一句用不了这么多；不设上限的话，
            // 一个巨大的 body 就能把插件（宿主进程的一部分）的内存吃满。
            if (body.length > MAX_BODY_BYTES) {
              bodyTooBig = true;
              body = '';                 // 立刻释放已缓冲的部分
              reply(413, { ok: false, error: 'body too large' });
              // **不要 req.destroy()**：那样 `end` 不会触发、客户端只能拿到一个
              // 连接重置（状态码 -1），于是"被拒"在调用方看来成了"网络坏了"。
              // `resume()` 把剩下的读掉丢掉 —— 有上限、不缓冲。
              req.resume();
            }
          });
          req.on('end', async () => {
            if (bodyTooBig) {
              return;                    // 已经回过 413 了
            }
            let payload = {};
            try {
              payload = JSON.parse(body || '{}');
            } catch {
              /* 坏 body 当作空提问 */
            }
            const prompt = String(payload.text || '').trim();
            if (!prompt) {
              reply(400, { ok: false, error: '需要 text' });
              return;
            }

            // 桌宠会在请求里带上该生效的配置：提示词、轮数、是否配图、可用表情、
            // 指定的 provider/model。插件侧配置只作为兜底。
            const kind = payload.kind === 'whisper' ? 'whisper' : 'chat';
            const rounds = Number(payload.memoryRounds) || memoryRounds;
            const pool = memePool(payload.memes);
            const imageEnabled = payload.imageEnabled !== false;
            const route = { provider: payload.provider || '', model: payload.model || '' };

            if (kind === 'whisper') {
              // 额度给足：推理模型会先吃掉一部分额度用于 reasoning-delta，
              // 给小了正文就没位置了（实测 120 会让正文只剩两个字甚至全空）。
              const result = await askDetailed(payload.system || whisperPrompt, prompt, 800, route);
              if (!result.text) {
                // 把原因回传，桌宠会把它显示在气泡上——否则用户只看到"没反应"
                reply(200, { ok: true, text: '', image: '', error: result.error });
                return;
              }
              let image = '';
              if (imageEnabled && pool.length) {
                image = pool[Math.floor(Math.random() * pool.length)][0];
              }
              reply(200, { ok: true, text: result.text, image });
              return;
            }

            const history = memory
              .slice(-rounds * 2)
              .map((turn) => `${turn.role === 'user' ? '主人' : '你'}：${turn.text}`)
              .join('\n');
            const stickerList = pool.map(([key, desc]) => `${key}（${desc}）`).join('、');
            const system = '你是主人桌面上的Q版蓝发小女仆，正在被主人搭话。'
              + '回答要短（40字以内）、自然、口语化，温柔乖巧带点俏皮，不要解释你自己，不要提你是AI。'
              + (imageEnabled && stickerList
                ? `如果某个表情很贴切，可以在回答最后单独加上 [图:表情名]。可选：${stickerList}。`
                : '')
              + (history ? `\n最近的对话：\n${history}` : '');
            const raw = await ask(system, prompt, 1200, route);

            let text = raw;
            let image = '';
            const match = raw.match(/\[图[:：]\s*([^\]]+)\]/);
            if (match) {
              const key = match[1].trim();
              if (imageEnabled && pool.some(([k]) => k === key)) image = key;
              text = raw.replace(match[0], '').trim();
            }
            memory.push({ role: 'user', text: prompt });
            memory.push({ role: 'assistant', text });
            while (memory.length > rounds * 2) memory.shift();
            reply(200, { ok: true, text, image });
          });
        });
        server.on('error', (error) => {
          ctx.logger?.warn?.('dsh-pet-bridge: 模型端口 %s 不可用（%s）', selfPort, error?.message);
        });
        server.listen(selfPort, '127.0.0.1');
        ctx.on('dispose', () => server.close());
      })
      .catch(() => {});
  };

  // ------------------------------------------------------------ 会话事件 --
  safeOn('agent/status', ({ status }) => {
    if (status === 'running') {
      toolsThisTurn = 0;
      clearBusy();
      if (!flashTimer) sendMood('thinking');
      return;
    }
    // 一轮结束：累计一次轮次，并在庆祝之后报一次用量档位。
    // `reportUsage` 是 async（要取余额），出错必须被 guard 吞掉——它是 Promise，
    // 直接传进 setTimeout 的话 rejection 会变成 unhandled rejection。
    totalTurns += 1;
    if (toolsThisTurn > 0) flash('celebrating');
    else sendMood('idle');
    setTimeout(guard('报用量', reportUsage), FLASH_MS + 400);
  });

  safeOn('agent/error', () => {
    flash('sighing');
  });

  safeOn('session/event', (_session, event) => {
    const type = event?.type;

    if (type === 'approval/asked') {
      sendMood('thinking');
      return;
    }

    if (type === 'tools/result' || type === 'tool/result') {
      toolsThisTurn += 1;
      totalSteps += 1;
      // 一次工具返回之后 Agent 通常还要继续想，先标 filing；若之后没有新的工具
      // 调用，再衰减回 thinking。
      sendMood('filing');
      clearBusy();
      busyTimer = setTimeout(() => {
        busyTimer = null;
        sendMood('thinking');
      }, BUSY_DECAY_MS);
      return;
    }

    if (type === 'tools/call' || type === 'tool/call') {
      clearBusy();
      sendMood('busy');
      // **必须给 busy 一个衰减兜底**：原先这里设了 busy 却不设定时器，靠下一次
      // `tools/result` 或 `agent/status idle` 来收尾。但一轮如果以错误/中断结束，
      // 这两个都可能不来，宠物就永久卡在"忙碌点按"这一个动作上（用户报"停下来只有
      // 一个动作"）。这里安排一个远大于单次工具耗时的兜底，若期间没有新的状态刷新
      // 就退回 idle。
      scheduleBusyWatchdog();
    }
  });

  startServer();

  ctx.on('dispose', () => {
    clearBusy();
    if (flashTimer) clearTimeout(flashTimer);
  });
}
