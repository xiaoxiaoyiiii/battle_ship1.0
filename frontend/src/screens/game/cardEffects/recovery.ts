import type { EffectCell, EffectPoint, EffectRect, RecoveryEffectKind } from './types'
  const TAU = Math.PI * 2;
  const clamp = (v: number, a = 0, b = 1) => Math.min(b, Math.max(a, v));
  const ease = (v: number) => 1 - Math.pow(1 - clamp(v), 3);
  const smooth = (a: number, b: number, v: number) => { const t = clamp((v - a) / (b - a)); return t * t * (3 - 2 * t); };
  function rng(n: number, seed: number) {
    const x = Math.sin(n * 123.917 + seed * 0.00731) * 43758.5453;
    return x - Math.floor(x);
  }
  function line(ctx: CanvasRenderingContext2D, pts: readonly EffectPoint[], color: string, width: number, blur = 0) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.shadowColor = color;
    ctx.shadowBlur = blur;
    ctx.stroke();
    ctx.shadowBlur = 0;
  }
  function ellipse(ctx: CanvasRenderingContext2D, x: number, y: number, rx: number, ry: number, color: string, width = 1.5) {
    ctx.beginPath(); ctx.ellipse(x, y, Math.max(rx, .01), Math.max(ry, .01), 0, 0, TAU);
    ctx.strokeStyle = color; ctx.lineWidth = width; ctx.stroke();
  }
  function glow(ctx: CanvasRenderingContext2D, x: number, y: number, rx: number, ry: number, inner: string, outer?: string) {
    ctx.save(); ctx.translate(x, y); ctx.scale(rx, ry);
    const g = ctx.createRadialGradient(0, 0, 0, 0, 0, 1);
    g.addColorStop(0, inner); g.addColorStop(1, outer || 'rgba(255,255,255,0)');
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, 1, 0, TAU); ctx.fill(); ctx.restore();
  }
  function sparkle(ctx: CanvasRenderingContext2D, x: number, y: number, s: number, angle: number, color: string) {
    ctx.save(); ctx.translate(x, y); ctx.rotate(angle);
    ctx.fillStyle = color; ctx.beginPath();
    ctx.moveTo(0, -s * 1.7); ctx.lineTo(s * .23, -s * .2);
    ctx.lineTo(s, 0); ctx.lineTo(s * .23, s * .2);
    ctx.lineTo(0, s * 1.7); ctx.lineTo(-s * .23, s * .2);
    ctx.lineTo(-s, 0); ctx.lineTo(-s * .23, -s * .2); ctx.closePath(); ctx.fill(); ctx.restore();
  }
  function cellGeometry(cell: EffectCell) {
    return { x: cell.cx ?? (cell.x + cell.w / 2), y: cell.cy ?? (cell.y + cell.h / 2), u: Math.max(25, Math.min(cell.w || 70, cell.h || 70)) };
  }
  function flash(ctx: CanvasRenderingContext2D, x: number, y: number, u: number, p: number, tint: string) {
    const f = Math.exp(-Math.pow((p - .45) / .045, 2));
    if (f < .002) return;
    ctx.save(); ctx.globalAlpha *= f;
    glow(ctx, x, y, u * 1.75, u * 1.3, tint, 'rgba(255,255,255,0)');
    sparkle(ctx, x, y, u * .72, 0, 'rgba(255,255,245,.92)');
    ctx.restore();
  }

  function revive(ctx: CanvasRenderingContext2D, p: number, cells: readonly EffectCell[], seed: number, mode: 'revive' | 'heal') {
    const isHeal = mode === 'heal';
    const base = isHeal ? [170, 255, 198] : [255, 226, 148];
    const rgb = base.join(',');
    cells.forEach((cell, k) => {
      const { x, y, u } = cellGeometry(cell);
      const settle = ease(p / .45);
      const release = clamp((p - .45) / .55);
      const alpha = smooth(0, .12, p) * (1 - smooth(.72, 1, p));
      const inheritedAlpha = ctx.globalAlpha;
      ctx.save(); ctx.globalAlpha *= alpha;
      ctx.globalCompositeOperation = 'screen';
      glow(ctx, x, y + u * .18, u * 1.4, u * .6, `rgba(${rgb},.34)`);
      glow(ctx, x, y - u * .6, u * .62, u * 1.7, `rgba(${rgb},.18)`);
      // 苏生形成直立光柱；疗愈沿船体织出两道生长光丝。
      if (!isHeal) {
        const beamH = u * (1 + 2.5 * settle + .8 * release);
        const beamW = u * (.18 + .12 * Math.sin(p * Math.PI));
        const beam = ctx.createLinearGradient(x, y, x, y - beamH);
        beam.addColorStop(0, 'rgba(255,250,205,.9)');
        beam.addColorStop(.38, 'rgba(255,226,143,.33)');
        beam.addColorStop(1, 'rgba(255,226,143,0)');
        ctx.fillStyle = beam;
        ctx.beginPath(); ctx.moveTo(x - beamW, y + u * .15); ctx.lineTo(x - beamW * .28, y - beamH);
        ctx.lineTo(x + beamW * .28, y - beamH); ctx.lineTo(x + beamW, y + u * .15); ctx.closePath(); ctx.fill();
        line(ctx, [[x, y + u * .12], [x, y - beamH * .86]], 'rgba(255,255,227,.76)', u * .025, 9);
      }
      const strands = isHeal ? 2 : 1;
      for (let s = 0; s < strands; s++) {
        const pts: EffectPoint[] = [];
        const phase = s * Math.PI + p * TAU * 1.5;
        for (let i = 0; i <= 54; i++) {
          const q = i / 54;
          const radius = u * (.50 - q * .24) * settle;
          pts.push([x + Math.cos(q * TAU * 1.35 + phase) * radius, y + u * .25 - q * u * (isHeal ? 1.8 : 2.1) + Math.sin(q * TAU * 1.35 + phase) * u * .12]);
        }
        line(ctx, pts, isHeal ? 'rgba(162,255,187,.82)' : 'rgba(255,226,149,.66)', isHeal ? 2.3 : 1.5, 7);
      }
      for (let r = 0; r < (isHeal ? 2 : 3); r++) {
        const q = clamp(p * 1.45 - r * .12);
        const a = Math.sin(q * Math.PI);
        ctx.globalAlpha = inheritedAlpha * alpha * a;
        ellipse(ctx, x, y + u * .2 - r * u * .08, u * (.42 + q * .8), u * (.11 + q * .17), `rgba(${rgb},.8)`, 1.4);
      }
      ctx.globalAlpha = inheritedAlpha * alpha;
      for (let i = 0; i < (isHeal ? 32 : 40); i++) {
        const n = i + k * 97;
        const speed = .55 + rng(n + 11, seed) * .5;
        const life = clamp((p - rng(n, seed) * .20) * speed * 1.25);
        const th = rng(n + 20, seed) * TAU + life * (isHeal ? 4 : 1.1);
        const radius = u * (.20 + rng(n + 44, seed) * .50) * (isHeal ? 1 - life * .3 : 1);
        const px = x + Math.cos(th) * radius;
        const py = y + u * .30 - life * u * (1.8 + rng(n + 31, seed) * 2.2) + Math.sin(th) * radius * .25;
        ctx.globalAlpha = inheritedAlpha * alpha * Math.sin(Math.PI * clamp(life * 1.2));
        if (isHeal && i % 3 === 0) {
          ctx.save(); ctx.translate(px, py); ctx.rotate(th - Math.PI / 2);
          ctx.fillStyle = 'rgba(190,255,194,.85)'; ctx.beginPath();
          ctx.ellipse(0, 0, 2.8, 6.2, .6, 0, TAU); ctx.fill(); ctx.restore();
        } else sparkle(ctx, px, py, 1.5 + rng(n + 17, seed) * 2.7, th, `rgba(${rgb},.92)`);
      }
      ctx.globalAlpha = inheritedAlpha * alpha;
      flash(ctx, x, y - u * .05, u, p, isHeal ? 'rgba(204,255,213,.67)' : 'rgba(255,239,171,.67)');
      ctx.restore();
    });
  }

  function lastChance(ctx: CanvasRenderingContext2D, p: number, cells: readonly EffectCell[], seed: number) {
    cells.forEach((cell, k) => {
      const { x, y, u } = cellGeometry(cell);
      const a = smooth(0, .06, p) * (1 - smooth(.76, 1, p));
      ctx.save(); ctx.globalAlpha *= a; ctx.globalCompositeOperation = 'screen';
      glow(ctx, x, y, u * 1.7, u * .8, 'rgba(255,214,117,.32)');
      // 三束光由海面外回流到新舰位置，随后成为向上冲起的生命光柱。
      for (let side = 0; side < 3; side++) {
        const theta = [-2.55, -.6, -1.56][side];
        const t = ease(clamp(p / .45));
        const pts: EffectPoint[] = [];
        for (let i = 0; i <= 45; i++) {
          const q = clamp(t - .34 + i / 45 * .34);
          const r = (1 - q) * u * 3.2;
          pts.push([x + Math.cos(theta + q * .7 * (side === 0 ? -1 : 1)) * r, y + Math.sin(theta) * r * .58 - Math.sin(q * Math.PI) * u * 1.2]);
        }
        if (p < .53) {
          line(ctx, pts, 'rgba(255,218,136,.88)', 3, 12);
          const end = pts[pts.length - 1];
          glow(ctx, end[0], end[1], u * .28, u * .28, 'rgba(255,252,216,.96)');
        }
      }
      const ascent = clamp((p - .42) / .4);
      if (ascent > 0) {
        const h = u * (1 + ascent * 3.2);
        const g = ctx.createLinearGradient(x, y, x, y - h);
        g.addColorStop(0, 'rgba(255,251,222,.95)'); g.addColorStop(.32, 'rgba(255,218,123,.5)'); g.addColorStop(1, 'rgba(255,210,130,0)');
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.moveTo(x - u * .33, y); ctx.quadraticCurveTo(x - u * .17, y - h * .45, x, y - h);
        ctx.quadraticCurveTo(x + u * .17, y - h * .45, x + u * .33, y); ctx.closePath(); ctx.fill();
        for (let j = 0; j < 5; j++) {
          const offset = (j - 2) * u * .18;
          line(ctx, [[x + offset, y - ascent * u * .5], [x + offset * .4, y - h * (.60 + j * .06)]], 'rgba(255,239,177,.74)', j === 2 ? 3 : 1.4, 7);
        }
        const ring = ease(ascent);
        ellipse(ctx, x, y + u * .15, u * (.40 + ring * .85), u * (.12 + ring * .22), 'rgba(255,222,137,.88)', 2.5);
        for (let i = 0; i < 32; i++) {
          const angle = rng(i + k * 57, seed) * TAU;
          const r = u * (.15 + rng(i + 31, seed) * 1.3) * ascent;
          sparkle(ctx, x + Math.cos(angle) * r, y - ascent * u * (1 + rng(i + 40, seed) * 2) + Math.sin(angle) * r * .35, 1.5 + rng(i + 63, seed) * 2.2, angle, 'rgba(255,239,181,.88)');
        }
      }
      flash(ctx, x, y, u * 1.1, p, 'rgba(255,244,186,.85)');
      ctx.restore();
    });
  }

  function hexPath(ctx: CanvasRenderingContext2D, x: number, y: number, rx: number, ry: number) {
    ctx.beginPath();
    for (let i = 0; i < 6; i++) {
      const a = -Math.PI / 2 + i * TAU / 6;
      const px = x + Math.cos(a) * rx, py = y + Math.sin(a) * ry;
      if (!i) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
  }
  function shield(ctx: CanvasRenderingContext2D, p: number, cells: readonly EffectCell[]) {
    const spread = ease(p / .43);
    const a = smooth(0, .12, p) * (1 - smooth(.72, 1, p));
    cells.forEach((cell, k) => {
      const { x, y, u } = cellGeometry(cell);
      const cy = y - u * .28;
      const rx = u * .76 * spread, ry = u * .90 * spread;
      ctx.save(); ctx.globalAlpha *= a;
      glow(ctx, x, y + u * .22, u * 1.3, u * .48, 'rgba(255,222,138,.30)');
      const g = ctx.createLinearGradient(x - rx, cy - ry, x + rx, cy + ry);
      g.addColorStop(0, 'rgba(255,245,184,.30)'); g.addColorStop(.4, 'rgba(171,230,239,.035)'); g.addColorStop(1, 'rgba(255,210,107,.17)');
      hexPath(ctx, x, cy, rx, ry); ctx.fillStyle = g; ctx.fill();
      ctx.save(); ctx.clip();
      const unit = u * .16;
      ctx.lineWidth = .8; ctx.strokeStyle = 'rgba(255,231,164,.26)';
      for (let row = -5; row < 6; row++) for (let col = -4; col < 5; col++) {
        const hx = x + col * unit * 1.72 + (row % 2) * unit * .86;
        const hy = cy + row * unit * 1.5;
        hexPath(ctx, hx, hy, unit, unit); ctx.stroke();
      }
      const sweep = cy + ry * (1.6 - p * 4.6);
      const sheen = ctx.createLinearGradient(x, sweep - u * .22, x, sweep + u * .22);
      sheen.addColorStop(0, 'rgba(255,250,210,0)'); sheen.addColorStop(.48, 'rgba(255,250,210,.4)'); sheen.addColorStop(1, 'rgba(255,250,210,0)');
      ctx.fillStyle = sheen; ctx.fillRect(x - rx, cy - ry, rx * 2, ry * 2);
      ctx.restore();
      ctx.shadowColor = '#ffe6a5'; ctx.shadowBlur = 13;
      hexPath(ctx, x, cy, rx, ry); ctx.strokeStyle = 'rgba(255,231,161,.94)'; ctx.lineWidth = 2.4; ctx.stroke();
      ctx.shadowBlur = 0;
      hexPath(ctx, x, cy, rx * .89, ry * .91); ctx.strokeStyle = 'rgba(255,247,208,.42)'; ctx.lineWidth = 1; ctx.stroke();
      for (let i = 0; i < 6; i++) {
        const th = -Math.PI / 2 + i * TAU / 6;
        sparkle(ctx, x + Math.cos(th) * rx, cy + Math.sin(th) * ry, 3.1, th, 'rgba(255,249,211,.9)');
      }
      // 护罩从海面升起，保留后缘和前缘以呈现深度。
      ellipse(ctx, x, y + u * .26, u * .79 * spread, u * .23 * spread, 'rgba(255,225,145,.60)', 1.5);
      flash(ctx, x, cy, u * .8, p, 'rgba(255,242,180,.43)');
      ctx.restore();
    });
  }

  function sanctuary(ctx: CanvasRenderingContext2D, p: number, rect: EffectRect, seed: number) {
    const q = ease(p / .45);
    const a = smooth(0, .12, p) * (1 - smooth(.72, 1, p));
    const x = rect.x + rect.w / 2, baseY = rect.y + rect.h * .70;
    const rx = rect.w * .58 * q, h = rect.h * .70 * q, ellipseH = rect.h * .17 * q;
    const inheritedAlpha = ctx.globalAlpha;
    ctx.save(); ctx.globalAlpha *= a;
    glow(ctx, x, baseY, rx * 1.13, ellipseH * 1.6, 'rgba(247,221,147,.18)');
    ctx.beginPath(); ctx.moveTo(x - rx, baseY);
    ctx.bezierCurveTo(x - rx, baseY - h * .80, x - rx * .54, baseY - h, x, baseY - h);
    ctx.bezierCurveTo(x + rx * .54, baseY - h, x + rx, baseY - h * .80, x + rx, baseY);
    ctx.ellipse(x, baseY, Math.max(.1, rx), Math.max(.1, ellipseH), 0, 0, Math.PI);
    ctx.closePath();
    const fill = ctx.createLinearGradient(x, baseY - h, x, baseY + ellipseH);
    fill.addColorStop(0, 'rgba(255,235,168,.17)'); fill.addColorStop(.5, 'rgba(182,224,234,.025)'); fill.addColorStop(1, 'rgba(255,228,152,.14)');
    ctx.fillStyle = fill; ctx.fill();
    ctx.save(); ctx.clip();
    ctx.lineWidth = 1;
    // 经线随穹顶曲率改变；纬线只留背部细线，避免平面网罩感。
    for (let i = -3; i <= 3; i++) {
      const dx = i / 3;
      ctx.beginPath(); ctx.moveTo(x + dx * rx, baseY);
      ctx.bezierCurveTo(x + dx * rx * .95, baseY - h * .60, x + dx * rx * .44, baseY - h, x, baseY - h);
      ctx.strokeStyle = `rgba(255,230,161,${.16 + .10 * (1 - Math.abs(dx))})`; ctx.stroke();
    }
    for (let j = 1; j <= 5; j++) {
      const t = j / 6;
      const yy = baseY - h * t;
      const rw = rx * Math.sqrt(1 - t * t);
      ellipse(ctx, x, yy, rw, ellipseH * (1 - t) * .60, 'rgba(255,230,161,.18)', 1);
    }
    const scan = baseY + ellipseH - (h + ellipseH) * clamp((p - .12) / .50);
    const sheen = ctx.createLinearGradient(x, scan - 24, x, scan + 24);
    sheen.addColorStop(0, 'rgba(255,248,206,0)'); sheen.addColorStop(.5, 'rgba(255,248,206,.13)'); sheen.addColorStop(1, 'rgba(255,248,206,0)');
    ctx.fillStyle = sheen; ctx.fillRect(x - rx, baseY - h, rx * 2, h + ellipseH);
    ctx.restore();
    ctx.shadowColor = '#ffe5a4'; ctx.shadowBlur = 10;
    ctx.beginPath(); ctx.moveTo(x - rx, baseY);
    ctx.bezierCurveTo(x - rx, baseY - h * .80, x - rx * .54, baseY - h, x, baseY - h);
    ctx.bezierCurveTo(x + rx * .54, baseY - h, x + rx, baseY - h * .80, x + rx, baseY);
    ctx.strokeStyle = 'rgba(255,235,170,.76)'; ctx.lineWidth = 2.3; ctx.stroke(); ctx.shadowBlur = 0;
    ellipse(ctx, x, baseY, rx, ellipseH, 'rgba(255,225,151,.60)', 2.2);
    // 六枚支点从舰队海面托住穹顶。
    for (let i = 0; i < 6; i++) {
      const th = i * TAU / 6 + .25;
      const px = x + Math.cos(th) * rx, py = baseY + Math.sin(th) * ellipseH;
      glow(ctx, px, py, 18, 12, 'rgba(255,239,178,.75)');
      line(ctx, [[px, py], [px, py - 26 * q]], 'rgba(255,235,161,.60)', 1.5, 5);
    }
    for (let i = 0; i < 35; i++) {
      const xx = x + (rng(i, seed) - .5) * rx * 1.6;
      const yy = baseY - rng(i + 57, seed) * h * .85 - p * 50;
      const local = Math.sin(p * Math.PI) * (.3 + .7 * rng(i + 89, seed));
      ctx.globalAlpha = inheritedAlpha * a * local;
      sparkle(ctx, xx, yy, 1.5 + rng(i + 30, seed) * 2, rng(i + 40, seed), 'rgba(255,239,181,.82)');
    }
    ctx.globalAlpha = inheritedAlpha * a;
    const f = Math.exp(-Math.pow((p - .45) / .06, 2));
    glow(ctx, x, baseY - h, rx * .38, h * .34, `rgba(255,246,197,${f * .55})`);
    ctx.restore();
  }


/** public 视角只画整盘均匀光晕，不制造任何虚构中心或隐含落点。 */
export function drawPublicRecovery(ctx: CanvasRenderingContext2D,p: number,rect: EffectRect): void {
  if(p<=0||p>=1)return
  const fade=smooth(0,.15,p)*(1-smooth(.67,1,p))
  ctx.save();ctx.globalAlpha*=fade
  const gradient=ctx.createLinearGradient(rect.x,rect.y,rect.x,rect.y+rect.h)
  gradient.addColorStop(0,'#eedb9d20');gradient.addColorStop(.5,'#e3cd8a0a');gradient.addColorStop(1,'#e9ddab35')
  ctx.fillStyle=gradient;ctx.beginPath();ctx.roundRect(rect.x-8,rect.y-8,rect.w+16,rect.h+16,12);ctx.fill()
  ctx.strokeStyle='#e9d79a';ctx.lineWidth=1.2;ctx.shadowColor='#e8d898';ctx.shadowBlur=8;ctx.stroke();ctx.shadowBlur=0
  const inset=18*(1-smooth(0,.45,p))
  ctx.beginPath();ctx.roundRect(rect.x-8-inset,rect.y-8-inset,rect.w+16+inset*2,rect.h+16+inset*2,12);ctx.strokeStyle='#e9d79a55';ctx.stroke()
  ctx.restore()
}
export function drawRecovery(ctx: CanvasRenderingContext2D,kind: RecoveryEffectKind,p: number,rect: EffectRect,cells: readonly EffectCell[],seed=42): void {
  if(p<=0||p>=1)return
  ctx.save();ctx.lineCap='round';ctx.lineJoin='round'
  if(kind==='sanctuary')sanctuary(ctx,p,rect,seed)
  else if(!cells.length)drawPublicRecovery(ctx,p,rect)
  else if(kind==='revive'||kind==='heal')revive(ctx,p,cells,seed,kind)
  else if(kind==='last_chance')lastChance(ctx,p,cells,seed)
  else shield(ctx,p,cells)
  ctx.restore()
}
