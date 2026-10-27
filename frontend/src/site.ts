/** 官网渲染：按 design/ 设计稿 1:1 还原（导航/Hero/痛点/核心能力/FAQ/CTA/页脚）。 */

const NAV_ITEMS = [
  { label: "产品特性", href: "#features" },
  { label: "工作原理", href: "#how" },
  { label: "常见问题", href: "#faq" },
  { label: "技术文档", href: "/docs" },
];

const PAINS = [
  {
    icon: "🔁",
    title: "高频问题反复答",
    desc: "同一个问题一天答80遍，人力全耗在复制粘贴上，真正复杂的问题反而没人顾。",
  },
  {
    icon: "🤷",
    title: "答非所问气走客户",
    desc: "关键词匹配听不懂人话，“能退不”匹配不到退换货政策，客户三句话就失去耐心。",
  },
  {
    icon: "⛔",
    title: "该转人工时硬扛",
    desc: "涉及退款、赔偿、投诉还硬答，把小问题聊成大客诉，转人工又像断线一样全靠客户重讲。",
  },
];

const STEPS = [
  { no: "01", title: "知识库入库", desc: "FAQ问答对与政策文档分层入库，变体问法一起向量化。" },
  { no: "02", title: "双路混合检索", desc: "向量语义+BM25关键词双路召回，重排取Top 3。" },
  { no: "03", title: "置信度分级判断", desc: "高置信直接应答，中置信先确认，低置信不硬扛。" },
  { no: "04", title: "生成回答或转人工", desc: "命中则事实打底再幽默润色；未命中、高风险自动转人工。" },
];

const FAQS = [
  {
    q: "小答会不会一本正经地胡说八道？",
    a: "不会。回答必须100%来自知识库：生成前Prompt强约束，生成前再做可回答性校验，生成后核对关键事实。查不到就老实说查不到，并帮你转人工确认。",
  },
  {
    q: "客户说“转人工”会不会找不到人？",
    a: "不会冷场。转人工不是断线：排队状态实时可见，你可以先留言或继续问其他问题；人工上线后无缝接管，且已带上对话摘要与订单信息。",
  },
  {
    q: "能嵌入我们自己的官网吗？",
    a: "可以。前端是Web Component聊天组件，右下角悬浮按钮+气泡窗口，一行代码嵌入任意站点，支持React/Vue，样式可按品牌定制。",
  },
  {
    q: "知识库维护成本高吗？",
    a: "很低。维护一份Excel/JSON就是唯一数据源，改完一键重建索引；每周把点踩与转人工的Bad Case转成新FAQ，知识库越用越厚。",
  },
];

export function renderSite(root: HTMLElement) {
  root.innerHTML = `
    <nav class="nav">
      <div class="nav-inner">
        <a class="logo" href="#top">
          <span class="logo-icon">答</span>
          <span class="logo-name">小答</span>
        </a>
        <div class="nav-links">
          ${NAV_ITEMS.map((it) => `<a href="${it.href}">${it.label}</a>`).join("")}
        </div>
        <a class="btn btn-primary btn-sm" href="#cta">免费试用</a>
      </div>
    </nav>

    <header class="hero" id="top">
      <div class="hero-inner">
        <div class="hero-copy">
          <div class="hero-tag">RAG驱动的网页端客服Agent</div>
          <h1>自动解决80%咨询，<br/>该转人工时绝不硬扛。</h1>
          <p class="hero-desc">小答从知识库精准应答，轻松活泼、偶尔玩梗；没命中或碰上高风险问题，自动转人工，并把对话上下文一并带过去。</p>
          <div class="hero-actions">
            <a class="btn btn-primary" href="#cta">免费试用</a>
            <a class="btn btn-ghost" href="#how">看它怎么答</a>
          </div>
          <div class="hero-trust">全程披露AI身份 · 事实100%来自知识库 · 首字响应&lt;2秒</div>
        </div>
        <div class="hero-demo">
          <xd-chat-widget mode="inline"></xd-chat-widget>
        </div>
      </div>
    </header>

    <section class="problem" id="how">
      <div class="container">
        <div class="sec-label">为什么需要小答</div>
        <h2 class="sec-title-light">重复问题刷屏，客服却还在手动复制粘贴</h2>
        <p class="sec-sub-light">80%的咨询集中在20%的高频问题上。答慢了客户流失，硬扛着答错了客诉升级——这不是人力能扛住的仗。</p>
        <div class="pains">
          ${PAINS.map(
            (p) => `
            <div class="pain-card">
              <div class="pain-icon">${p.icon}</div>
              <div class="pain-title">${p.title}</div>
              <div class="pain-desc">${p.desc}</div>
            </div>`,
          ).join("")}
        </div>
        <div class="solution">小答的解法：能自动的高效自动，该转人工的绝不硬扛——幽默是调味料，解决问题才是主菜。</div>
        <div class="steps">
          ${STEPS.map(
            (s) => `
            <div class="step">
              <div class="step-no">${s.no}</div>
              <div class="step-title">${s.title}</div>
              <div class="step-desc">${s.desc}</div>
            </div>`,
          ).join("")}
        </div>
      </div>
    </section>

    <section class="features" id="features">
      <div class="container">
        <div class="sec-label">核心能力</div>
        <h2 class="sec-title">从命中到转人工，每一步都有章法</h2>

        <div class="feature-row">
          <div class="feature-copy">
            <h3>变体问法，也能精准命中</h3>
            <p>向量语义 + BM25 关键词双路召回，“能退不”“拆了包装能退不”都能对上「7天无理由退换」。相似度分级判断，没把握就先确认，绝不硬答。</p>
          </div>
          <div class="demo-card">
            <div class="demo-msg user">你们这破衣服能退不</div>
            <div class="demo-hit">命中 FAQ_001 · 退换货政策 · 相似度 0.91</div>
            <div class="demo-msg bot">支持7天无理由退换～不影响二次销售就行，拆封试用不影响，放心冲！</div>
          </div>
        </div>

        <div class="feature-row reverse">
          <div class="feature-copy">
            <h3>幽默是调味料，事实才是主菜</h3>
            <p>先出事实版回答，再做幽默润色，数字与规则锁定不动。知识库没有的绝不编造，防幻觉三层防线从生成前拦到生成后。严肃场景自动切回正经模式。</p>
          </div>
          <div class="prompt-card">
            <div class="prompt-title">System Prompt · 幽默控制</div>
            <div class="prompt-line">事实版：发货时效是48小时内</div>
            <div class="prompt-line prompt-humor">幽默版：正常48小时内就能让它出门找你～急单可以备注</div>
            <div class="prompt-lock">数字 / 时间 / 金额锁定，润色不许动</div>
            <div class="prompt-fallback">知识库查不到？→「这个问题我暂时没有查到准确信息，帮您转接人工客服确认一下哈～」</div>
          </div>
        </div>

        <div class="feature-row">
          <div class="feature-copy">
            <h3>该转人工时，绝不硬扛</h3>
            <p>情绪熔断、连续两轮未解决、高风险问题自动转人工。转接瞬间把问题类型、订单号、对话摘要打包给人工客服——客户不用再说一遍。</p>
          </div>
          <div class="demo-card">
            <div class="demo-msg user">我要投诉！东西坏了你们管不管</div>
            <div class="demo-msg bot">非常抱歉给您带来不好的体验！我马上帮您转接专人处理，您说的情况我都记下来了，稍等～</div>
            <div class="demo-queue">人工客服接入中 · 前面还有2位</div>
            <div class="demo-handover">问题类型：质量投诉 · 情绪等级：红灯（已加急）</div>
            <div class="demo-handover">对话摘要与订单信息已同步，无需重复描述</div>
          </div>
        </div>
      </div>
    </section>

    <section class="faq" id="faq">
      <div class="container">
        <h2 class="sec-title">常见问题</h2>
        <div class="faq-list">
          ${FAQS.map(
            (f) => `
            <details class="faq-item">
              <summary>${f.q}</summary>
              <p>${f.a}</p>
            </details>`,
          ).join("")}
        </div>
      </div>
    </section>

    <section class="cta" id="cta">
      <div class="container">
        <h2>让小答先顶上，<br/>人工只处理真正需要人的事。</h2>
        <p>30条核心FAQ就能起步，一周内跑通自动应答与转人工闭环。</p>
        <div class="cta-actions">
          <a class="btn btn-primary" href="#top">免费试用</a>
          <a class="btn btn-outline-light" href="/docs">查看接入文档</a>
        </div>
      </div>
    </section>

    <footer class="footer">
      <div class="container footer-grid">
        <div class="footer-brand">
          <a class="logo" href="#top"><span class="logo-icon">答</span><span class="logo-name">小答</span></a>
          <p>轻松活泼的AI客服，该转人工时绝不硬扛。</p>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">产品</div>
          <a href="#features">功能特性</a>
          <a href="#how">工作原理</a>
          <a href="#">更新日志</a>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">开发者</div>
          <a href="/docs">接入文档</a>
          <a href="/docs#api">API 参考</a>
          <a href="#features">Web Component</a>
        </div>
        <div class="footer-col">
          <div class="footer-col-title">支持</div>
          <a href="#faq">帮助中心</a>
          <a href="#cta">联系销售</a>
          <a href="/health">服务状态</a>
        </div>
      </div>
      <div class="container footer-bottom">
        Copyright 2026 小答智能客服 保留所有权利 · 本页对话示例仅用于产品演示
      </div>
    </footer>

    <xd-chat-widget mode="floating"></xd-chat-widget>
  `;

  // 导航滚动样式
  const nav = root.querySelector(".nav") as HTMLElement;
  const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 8);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
}
