/* Isolated visual prototypes. All data and interactions are local examples. */
const design = document.body.dataset.design;
const variants = {
  x: { name: 'C+ 精修竞技场', caption: '熟悉的竞技场，更清楚的主次。', title: '下一场，轮到你掌控。', sub: '一片未知海域，一手无限可能。', file: 'x-arena-evolved.html' },
  y: { name: '舰桥指挥台', caption: '海域在前，战术在手。', title: '指挥官，舰队已就绪。', sub: '锁定海域。部署战术。把握每一次交锋。', file: 'y-bridge.html' },
  z: { name: '专注竞技场', caption: '把注意力留给下一步。', title: '好好打一场。', sub: '选择你的节奏，即刻进入海域。', file: 'z-focus.html' }
};
const cfg = variants[design];
const glyphs = { compass:'<path d="M12 2 15 9 22 12 15 15 12 22 9 15 2 12 9 9Z"/>', shield:'<path d="m12 3 8 3v6c0 5-8 9-8 9S4 17 4 12V6Z"/><path d="m8 12 3 3 5-6"/>', aim:'<circle cx="12" cy="12" r="7"/><path d="M12 1v5m0 12v5M1 12h5m12 0h5"/>', ship:'<path d="m3 15 4 6h10l4-6-9-4Z M7 13V6h10v7M12 6V2M3 23h18"/>', radar:'<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><path d="M12 12 19 5M12 3v9h9"/>', bolt:'<path d="m14 2-9 12h6l-1 8 9-12h-6Z"/>', eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>', wave:'<path d="M2 8q5-6 10 0t10 0M2 14q5-6 10 0t10 0M2 20q5-6 10 0t10 0"/>' };
const icon = (name, cls='') => `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${glyphs[name] || glyphs.compass}</svg>`;
const cards = [
  {name:'硫磺火焰',speed:2,icon:'bolt',color:'coral',hint:'连片打击',desc:'选定可以连续连接的6个格子，对这6个格子释放硫磺火焰并强制击杀上面的所有战舰，可以直接击杀状态「无敌」和「盾牌」的战舰。'},
  {name:'神威！',speed:2,icon:'wave',color:'cyan',hint:'海域除外',desc:'选定己方或者对方棋盘上的3×3区域，将其中的战舰暂时除外，在下一个大回合开始时回归。若选定的是对方的棋盘且区域中只有一艘船，那么那艘船直接死亡。'},
  {name:'失灵！',speed:3,icon:'shield',color:'violet',hint:'连锁响应',desc:'无效化对方使用的上一张魔法卡，被影响的魔法卡必须为当前时段刚使用的。这张牌会受「看破」影响，但是不会影响看破。'},
  {name:'增援',speed:3,icon:'ship',color:'mint',hint:'补充舰队',desc:'召唤一艘战舰并选择部署在没有被对方打过的一个格子上。'},
  {name:'看破！',speed:2,icon:'eye',color:'gold',hint:'战术封锁',desc:'这张牌生效后，这一个大回合内，对方所有魔法卡都无效化。这张牌不受「失灵！」影响，但是会影响「失灵！」。'}
];
const pips = n => `<span class="pips" aria-label="剩余${n}艘">${Array.from({length:6},(_,i)=>`<i class="${i<n?'alive':''}"></i>`).join('')}</span>`;
const cardMarkup = (c,i) => `<button class="magic-card ${c.color}" data-card="${i}" aria-label="查看${c.name}详情"><span class="card-top"><span>普通魔法</span><b>${'◆'.repeat(c.speed)}</b></span><span class="card-art">${icon(c.icon)}<i></i></span><strong>${c.name}</strong><span class="card-hint">${c.hint}<span>速阶 ${c.speed}</span></span></button>`;
function board(own) {
  const hits = own ? [8,27] : [9,15,28]; const misses = own ? [3,14,22] : [2,7,21,31];
  return `<div class="sea-grid ${own?'own':'enemy'}" role="group" aria-label="${own?'己方':'对手'}6乘6海域"><span></span>${'ABCDEF'.split('').map(c=>`<span class="axis">${c}</span>`).join('')}${Array.from({length:36},(_,i)=>`${i%6===0?`<span class="axis">${Math.floor(i/6)+1}</span>`:''}<button class="cell ${hits.includes(i)?'hit':misses.includes(i)?'miss':own&&[6,17,25,33].includes(i)?'vessel':''}" data-cell="${i}" ${own?'disabled':''} aria-label="${'ABCDEF'[i%6]}${Math.floor(i/6)+1}${hits.includes(i)?' 已命中':misses.includes(i)?' 未命中':''}">${hits.includes(i)?'×':misses.includes(i)?'○':own&&[6,17,25,33].includes(i)?icon('ship'):''}</button>`).join('')}</div>`;
}
document.body.innerHTML = `
<div class="prototype-banner"><span>${design.toUpperCase()} / ${cfg.name}</span><span>交互示意 · 所有数值均为示例</span><a href="arena-next.html">比较三套方案 ↗</a></div>
<header class="topbar"><a class="brand" href="arena-next.html">${icon('compass')}<span>战舰棋<small>BATTLESHIP / ARENA</small></span></a><nav aria-label="主要导航"><button class="nav-home active" data-view="home">竞技场</button><button data-panel="leaderboard">排行榜</button><button data-panel="lobby">游戏大厅</button><button data-panel="collection">卡牌图鉴</button></nav><div class="top-status"><span class="online-dot"></span>12 位指挥官在线<span class="avatar tiny">舟</span></div></header>
<main class="screen home-screen" data-view="home">
 <div class="home-heading"><div><div class="eyebrow">${design==='y'?'FLEET COMMAND / 舰队指挥':'THE ARENA / 卡牌与海战'}</div><h1>${cfg.title}</h1><p>${cfg.sub}</p></div><span class="date-label">${cfg.caption}</span></div>
 <div class="home-layout">
 <aside class="profile panel"><div class="profile-cover"><span class="orbit"></span>${icon('ship')}<span class="cover-label">CAPTAIN / 012</span></div><div class="profile-content"><span class="tag gold-text">大副 II</span><h2>舰长阿 7</h2><p>每一手，都是新的可能。</p><div class="rank-value">1,240 <small>段位积分</small></div><div class="progress"><i></i></div><div class="split subtle"><span>距大副 I</span><span>160 分</span></div><div class="profile-stats"><div><b>42</b><span>总对局</span></div><div><b>68%</b><span>胜率</span></div><div><b>6</b><span>最长连胜</span></div></div><button class="quiet full" data-panel="profile">查看指挥官名片 ↗</button></div></aside>
 <section class="mode-column"><div class="section-title"><h2>开始对局</h2><span>CHOOSE YOUR BATTLE</span></div><button class="mode casual" data-mode="休闲匹配"><span class="mode-icon">${icon('aim')}</span><span><small>PLAY AT YOUR PACE</small><strong>休闲匹配</strong><span>随机邂逅一位对手，轻松来一局</span></span><b class="mode-arrow">↗</b></button><button class="mode ranked" data-mode="排位对战"><span class="mode-icon">${icon('shield')}</span><span><small>RISE THROUGH THE RANKS</small><strong>排位对战</strong><span>大副 II · 为下一次晋升而战</span></span><b class="mode-arrow">↗</b></button><div class="practice panel"><div>${icon('radar')}<span><b>人机训练</b><small>熟悉战术，试试新的打法</small></span></div><div class="difficulty" aria-label="人机难度">${['简单','普通','困难'].map(n=>`<button data-difficulty="${n}" aria-pressed="${n==='普通'}" class="${n==='普通'?'selected':''}">${n}</button>`).join('')}</div><button class="quiet" data-mode="人机训练">开始 →</button></div><div class="minor-modes"><button class="panel" data-panel="room"><span>自定义房间<small>与好友约一场</small></span><b>＋</b></button><button class="panel" data-panel="lobby"><span>游戏大厅<small>2 个房间等待加入</small></span><b>↗</b></button></div><div class="popular"><div class="section-title"><h2>全服热门卡</h2><button class="text-button" data-panel="collection">查看图鉴 →</button></div><div class="mini-cards">${cards.map(cardMarkup).join('')}</div></div></section>
 <aside class="intel"><section class="panel rank-panel"><div class="section-title"><h2>晋升航线</h2>${icon('compass')}</div><div class="rank-emblem">${icon('shield')}</div><strong>向着大副 I</strong><p>每一场交锋，都在积累。</p><div class="rank-step"><span class="step-dot"></span><span>大副 I</span><b>1,400</b></div><div class="rank-step current"><span class="step-dot"></span><span>大副 II · 当前</span><b>1,240</b></div><div class="rank-step"><span class="step-dot done"></span><span>三副</span><b>900</b></div></section><section class="panel achievement-panel"><div class="section-title"><h2>最近解锁</h2><span>02</span></div><div class="achievement">${icon('shield')}<span><b>首胜</b><small>属于你的第一场胜利</small></span><span class="gold-text">✓</span></div><div class="achievement">${icon('bolt')}<span><b>五连胜</b><small>势不可挡的指挥官</small></span><span class="gold-text">✓</span></div></section><div class="home-note">${icon('wave')}<p>海面之下，是未知。<br>手牌之间，是可能。</p></div></aside>
 </div>
</main>
<main class="screen game-screen" data-view="game" hidden>
 <div class="match-strip panel"><div class="opponent"><span class="avatar">凛</span><div><b>凛冬海域</b><small>对手 · 剩余 3 艘 ${pips(3)}</small></div></div><div class="turn"><span class="live-dot"></span><b>你的回合</b><span>攻击阶段</span></div><div class="round">ROUND <b>08</b><button class="quiet" data-view="home">离开演示</button></div></div>
 <div class="battle-layout"><section class="board-panel own-panel panel"><div class="section-title"><h2><span class="cyan-dot"></span>你的海域</h2><span>剩余 4 / 6 艘</span></div>${board(true)}<div class="board-foot"><span>舰长阿 7</span>${pips(4)}<span>蓝色为存活舰船</span></div></section><section class="board-panel target-panel panel"><div class="section-title"><h2>${icon('aim')}对手海域</h2><span class="target-status">选择一个坐标</span></div>${board(false)}<div class="board-foot"><span><i class="legend-hit"></i>命中</span><span><i class="legend-miss"></i>落空</span><span>已探明 7 / 36 格</span></div></section><aside class="battle-intel"><section class="panel chain-panel"><div class="section-title"><h2>连锁轨道</h2><span class="tag">结算示例</span></div><div class="chain-line"><div class="chain-item"><span class="chain-number">02</span>${icon('shield')}<span><b>失灵！</b><small>你 · 速阶 3</small></span></div><div class="chain-item muted"><span class="chain-number">01</span>${icon('wave')}<span><b>神威！</b><small>对手 · 速阶 2</small></span></div></div><p>后发先结算 · 失灵！无效化神威！</p></section><section class="panel field-panel"><div class="eyebrow">FIELD MAGIC</div><h3>${icon('wave')}场地魔法</h3><p>当前没有生效的场地魔法</p></section><button class="quiet full log-toggle" data-panel="log">对局记录 <span>↗</span></button></aside></div>
 <section class="hand-zone panel"><div class="hand-meta"><div class="eyebrow">YOUR TACTICS</div><h2>你的手牌 <span>5</span></h2><p>点击卡牌查看详情</p><span class="tag">速阶 ◆ ◆◆ ◆◆◆</span></div><div class="hand-cards">${cards.map(cardMarkup).join('')}</div><div class="action-area"><span class="subtle">本回合剩余攻击 <b>1</b></span><div class="selection" aria-live="polite">在对手海域选择坐标</div><button id="fire" class="primary" disabled>确认攻击 ${icon('aim')}</button><button id="end-turn" class="quiet">结束回合 →</button></div></section>
</main>
<footer id="demo-switcher"><span>${design.toUpperCase()} / ${cfg.name}</span><div class="view-buttons"><button data-view="home" class="active">首页</button><button data-view="game">对局</button></div><div class="variant-links">${Object.entries(variants).map(([key,v])=>`<a class="${key===design?'active':''}" href="${v.file}">${key.toUpperCase()}</a>`).join('')}<a href="c-arena.html">原 C ↗</a></div></footer>
<dialog id="detail"><form method="dialog"><button class="close" aria-label="关闭">×</button></form><div id="detail-content"></div></dialog><div id="toast" role="status"></div>`;
window.__demoViews = ['home','game'];
window.__demoErrors = [];
window.addEventListener('error', e => window.__demoErrors.push(e.message));
window.setDemoView = view => {
  document.querySelectorAll('.screen').forEach(el => el.hidden = el.dataset.view !== view);
  document.querySelectorAll('[data-view]').forEach(el => {if(el.tagName==='BUTTON') el.classList.toggle('active',el.dataset.view===view);});
  document.body.classList.toggle('in-game',view==='game');
};
let toastTimer;
function toast(message) { const el=document.querySelector('#toast'); el.textContent=message; el.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.classList.remove('show'),3000); }
function showPanel(content) {document.querySelector('#detail-content').innerHTML=content;document.querySelector('#detail').showModal();}
const panels = {
  leaderboard:'<div class="eyebrow">LEADERBOARD / 示例</div><h2>海域排行榜</h2><div class="list-row"><b>01　长夜灯塔</b><span>1,860 分</span></div><div class="list-row"><b>02　凛冬海域</b><span>1,560 分</span></div><div class="list-row"><b>03　舰长阿 7</b><span>1,240 分</span></div>',
  lobby:'<div class="eyebrow">LOBBY / 示例</div><h2>一起出海</h2><div class="list-row"><span>周末来一局 · 1 / 2</span><button class="quiet" data-mode="好友房间">体验对局 →</button></div><div class="list-row"><span>魔法卡练习 · 1 / 2</span><button class="quiet" data-mode="好友房间">体验对局 →</button></div>',
  room:'<div class="eyebrow">PRIVATE ROOM / 示例</div><h2>好友房间</h2><p>示例房间号</p><div class="room-code">7 2 0 8 6 1</div><p>此房间仅展示 UI，不会创建真实房间。</p><button class="primary" data-mode="好友房间">进入对局演示 →</button>',
  profile:'<div class="eyebrow">CAPTAIN PROFILE / 示例</div><h2>舰长阿 7</h2><p>大副 II · Lv.12 · 1,240 分</p><div class="list-row"><span>总对局</span><b>42</b></div><div class="list-row"><span>胜率</span><b>68%</b></div><div class="list-row"><span>最长连胜</span><b>6</b></div>',
  log:'<div class="eyebrow">BATTLE LOG / 示例</div><h2>对局记录</h2><div class="list-row">08 · 你进入攻击阶段</div><div class="list-row">07 · 失灵！无效化神威！</div><div class="list-row">07 · 你使用失灵！响应</div><div class="list-row">07 · 对手使用神威！</div>'
};
let selected=null;
document.addEventListener('click', e => {
  const btn=e.target.closest('button');if(!btn)return;
  if(['leaderboard','lobby','collection','profile','room'].includes(btn.dataset.panel)){
    location.href='arena-suite.html?view='+btn.dataset.panel;return;
  }
  if(btn.dataset.view) window.setDemoView(btn.dataset.view);
  if(btn.dataset.mode){document.querySelector('#detail').close();window.setDemoView('game');toast(`${btn.dataset.mode} · 已进入示例对局`);}
  if(btn.dataset.difficulty){document.querySelectorAll('[data-difficulty]').forEach(el=>{el.classList.toggle('selected',el===btn);el.setAttribute('aria-pressed',String(el===btn));});}
  if(btn.dataset.panel==='collection')showPanel(`<div class="eyebrow">CARD CODEX / 示例</div><h2>你的战术，由你选择</h2><div class="collection-cards">${cards.map(cardMarkup).join('')}</div><p>点击任意卡牌阅读效果。</p>`);
  else if(btn.dataset.panel)showPanel(panels[btn.dataset.panel]);
  if(btn.dataset.card!==undefined){const c=cards[Number(btn.dataset.card)];showPanel(`<div class="card-detail ${c.color}"><div class="detail-art">${icon(c.icon)}</div><div class="eyebrow">普通魔法 / 速阶 ${c.speed}</div><h2>${c.name}</h2><p>${c.desc}</p><small>此演示提供阅读与选格体验，卡牌效果未接入对局规则。</small></div>`);}
  if(btn.matches('.enemy .cell')&&!btn.classList.contains('hit')&&!btn.classList.contains('miss')){document.querySelectorAll('.cell.selected').forEach(el=>el.classList.remove('selected'));btn.classList.add('selected');selected=btn;const i=Number(btn.dataset.cell),pos='ABCDEF'[i%6]+(Math.floor(i/6)+1);document.querySelector('.selection').textContent=`目标已锁定 · ${pos}`;document.querySelector('.target-status').textContent=pos+' · 待确认';document.querySelector('#fire').disabled=false;}
  if(btn.id==='fire'&&selected){selected.classList.remove('selected');selected.classList.add('miss');selected.textContent='○';selected.setAttribute('aria-label',selected.getAttribute('aria-label')+' 未命中');selected=null;btn.disabled=true;document.querySelector('.selection').textContent='演示结果：未命中，可继续选格';document.querySelector('.target-status').textContent='选择下一个坐标';const count=document.querySelectorAll('.enemy .hit,.enemy .miss').length;document.querySelector('.target-panel .board-foot span:last-child').textContent=`已探明 ${count} / 36 格`;toast('攻击交互演示 · 此次结果预设为未命中');}
  if(btn.id==='end-turn')toast('回合切换交互示意 · 未连接真实对局');
});
document.querySelector('#detail').addEventListener('click',e=>{if(e.target===e.currentTarget)e.currentTarget.close();});
window.setDemoView(new URLSearchParams(location.search).get('view')==='game'?'game':'home');
