import type { CardEffectFrame, CardEffectGeometry, EffectCell, EffectPoint, EffectRect } from './types'
import { clearElementCaches, drawElements, warmElementCaches } from './elements'
import { drawRecovery } from './recovery'
export type { CardEffectFrame, CardEffectGeometry, CardEffectKind, EffectCell, EffectRect } from './types'

const TAU=Math.PI*2
const clamp=(x: number,a=0,b=1)=>Math.max(a,Math.min(b,x))
const mix=(a: number,b: number,p: number)=>a+(b-a)*p
const smooth=(a: number,b: number,x: number)=>{const p=clamp((x-a)/(b-a));return p*p*(3-2*p)}
const rnd=(i: number,s=1)=>{const n=Math.sin(i*127.1+s*311.7)*43758.5453;return n-Math.floor(n)}
const center=(r: EffectRect): EffectPoint=>[r.x+r.w/2,r.y+r.h/2]
const validRect=(r: EffectRect)=>[r.x,r.y,r.w,r.h].every(Number.isFinite)&&r.w>0&&r.h>0
const normalizeRect=(r: EffectRect,u: number): EffectRect=>({x:r.x/u,y:r.y/u,w:r.w/u,h:r.h/u})
const normalizeCell=(c: EffectCell,u: number): EffectCell=>({...normalizeRect(c,u),cx:c.cx/u,cy:c.cy/u,gx:c.gx,gy:c.gy})

function line(ctx: CanvasRenderingContext2D,pts: readonly EffectPoint[],color: string,width=2,blur=0): void {
  if(pts.length<2)return
  ctx.beginPath();ctx.moveTo(...pts[0]);for(const p of pts.slice(1))ctx.lineTo(...p)
  ctx.strokeStyle=color;ctx.lineWidth=width;ctx.shadowColor=color;ctx.shadowBlur=blur;ctx.stroke();ctx.shadowBlur=0
}
function glow(ctx: CanvasRenderingContext2D,x: number,y: number,r: number,color: string,alpha=1): void {
  if(r<=0||alpha<=0)return
  ctx.save();ctx.globalAlpha*=alpha
  const g=ctx.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,color);g.addColorStop(1,'transparent')
  ctx.fillStyle=g;ctx.fillRect(x-r,y-r,r*2,r*2);ctx.restore()
}
function ellipse(ctx: CanvasRenderingContext2D,x: number,y: number,rx: number,ry: number,color: string,width=2): void {
  ctx.beginPath();ctx.ellipse(x,y,Math.max(.01,rx),Math.max(.01,ry),0,0,TAU);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke()
}
function particles(ctx: CanvasRenderingContext2D,x: number,y: number,age: number,color: string,count=65,power=1,seed=1): void {
  if(age<0||age>.7)return
  ctx.save();ctx.globalAlpha*=Math.max(0,1-age/.7)**1.5;ctx.fillStyle=color
  for(let i=0;i<count;i++){
    const a=TAU*rnd(i,seed),v=(50+220*rnd(i+45,seed))*power
    ctx.save();ctx.translate(x+Math.cos(a)*age*v,y+Math.sin(a)*age*v+age*age*80);ctx.rotate(a+age*3)
    ctx.fillRect(-1.2,-1,1.5+rnd(i+99,seed)*3,3+rnd(i+44,seed)*8);ctx.restore()
  }
  ctx.restore()
}
function shock(ctx: CanvasRenderingContext2D,x: number,y: number,age: number,color: string,size=190): void {
  if(age<0||age>.65)return
  ctx.save();ctx.globalAlpha*=(1-age/.65)**2;ellipse(ctx,x,y,10+age*size,5+age*size*.46,color,3*(1-age/.65)+.4);ctx.restore()
}
function blast(ctx: CanvasRenderingContext2D,x: number,y: number,age: number,seed: number): void {
  if(age<0||age>.85)return
  ctx.save();const boom=Math.exp(-age*7),spread=1-Math.exp(-age*13)
  for(let i=0;i<9;i++){
    const a=TAU*rnd(i,seed),r=(10+32*rnd(i+9,seed))*spread,px=x+Math.cos(a)*r,py=y+Math.sin(a)*r*.55-age*38,sz=(17+17*rnd(i+24,seed))*(.45+spread)
    const g=ctx.createRadialGradient(px,py,0,px,py,sz);g.addColorStop(0,'#fff4c8');g.addColorStop(.22,'#ffd47d');g.addColorStop(.54,'#fb782f');g.addColorStop(.82,'#b9361a99');g.addColorStop(1,'#87331b00')
    ctx.globalAlpha=boom*.96;ctx.fillStyle=g;ctx.fillRect(px-sz,py-sz,sz*2,sz*2)
  }
  for(let i=0;i<11;i++){
    const a=TAU*rnd(i+17,seed),r=(12+36*rnd(i+61,seed))*spread,px=x+Math.cos(a)*r,py=y+Math.sin(a)*r*.42-age*48,sz=(18+22*rnd(i+35,seed))*(.6+age)
    const g=ctx.createRadialGradient(px,py,0,px,py,sz);g.addColorStop(0,'#333b48bb');g.addColorStop(.55,'#242d3999');g.addColorStop(1,'#101b2c00')
    ctx.globalAlpha=smooth(.06,.22,age)*(1-smooth(.36,.85,age))*.65;ctx.fillStyle=g;ctx.fillRect(px-sz,py-sz,sz*2,sz*2)
  }
  for(let i=0;i<9;i++){
    const a=TAU*rnd(i+91,seed),v=70+110*rnd(i+73,seed),px=x+Math.cos(a)*age*v,py=y+Math.sin(a)*age*v*.45-age*75+age*age*100
    ctx.globalAlpha=(1-smooth(.2,.6,age))*.72;line(ctx,[[px,py],[px-Math.cos(a)*11,py+8]],'#d6f2ff',1.2,2)
  }
  ctx.restore()
}
function mean(cells: readonly EffectCell[],fallback: EffectRect): EffectPoint {
  if(!cells.length)return center(fallback)
  return [cells.reduce((v,c)=>v+c.cx,0)/cells.length,cells.reduce((v,c)=>v+c.cy,0)/cells.length]
}
function bomb(ctx: CanvasRenderingContext2D,p: number,source: EffectRect,target: EffectRect,cells: readonly EffectCell[],seed: number): void {
  if(!cells.length)return
  const [dx,dy]=mean(cells,target),a={x:source.x+source.w*.32,y:source.y+source.h*.76},b={x:target.x-105,y:target.y-195},c={x:target.x+target.w*.15,y:target.y-125}
  const pos=(q: number)=>{const n=1-q;return {x:n*n*n*a.x+3*n*n*q*b.x+3*n*q*q*c.x+q*q*q*dx,y:n*n*n*a.y+3*n*n*q*b.y+3*n*q*q*c.y+q*q*q*dy}}
  if(p<.45){
    const q=clamp(p/.45)
    for(let i=18;i>=0;i--){const t=q-i*.008;if(t<0)continue;const v=pos(t);glow(ctx,v.x,v.y,11+i*.7,'#70819b',.10*(1-i/20))}
    const v=pos(q),u=pos(Math.max(0,q-.005)),angle=Math.atan2(v.y-u.y,v.x-u.x)
    ctx.save();ctx.translate(v.x,v.y);ctx.rotate(angle);glow(ctx,-35,0,55,'#ff9c26',.6)
    const f=ctx.createLinearGradient(-85,0,-22,0);f.addColorStop(0,'#ff631800');f.addColorStop(.65,'#ff9d2cbb');f.addColorStop(1,'#fff4c8');ctx.fillStyle=f
    ctx.beginPath();ctx.moveTo(-24,-6);ctx.lineTo(-85-8*Math.sin(p*110),0);ctx.lineTo(-24,6);ctx.closePath();ctx.fill()
    const metal=ctx.createLinearGradient(0,-8,0,8);metal.addColorStop(0,'#f5faff');metal.addColorStop(.45,'#b2c6d7');metal.addColorStop(1,'#40546b');ctx.fillStyle=metal
    ctx.beginPath();ctx.moveTo(35,0);ctx.quadraticCurveTo(23,-8,-24,-7);ctx.lineTo(-30,-15);ctx.lineTo(-35,-15);ctx.lineTo(-31,0);ctx.lineTo(-35,15);ctx.lineTo(-30,15);ctx.lineTo(-24,7);ctx.quadraticCurveTo(23,8,35,0);ctx.fill();ctx.fillStyle='#e37135';ctx.fillRect(12,-6,4,12);ctx.restore()
  }
  // 从选区中心向两端推进，支持整行、整列及边界格数。
  const ordered=[...cells].sort((a,b)=>Math.hypot(a.cx-dx,a.cy-dy)-Math.hypot(b.cx-dx,b.cy-dy))
  ordered.forEach((c,i)=>{const age=(p-.45)*1.55-i*.035;if(age<0||age>.85)return;glow(ctx,c.cx,c.cy,95+age*30,'#ff5b1b',Math.exp(-age*6)*.8);blast(ctx,c.cx,c.cy,age,seed+i);shock(ctx,c.cx,c.cy,age,'#aee6ff',150);particles(ctx,c.cx,c.cy,age,'#ffc482',28,.7,seed+12+i)})
}
function vortex(ctx: CanvasRenderingContext2D,p: number,rect: EffectRect,cells: readonly EffectCell[],seed: number): void {
  const q=p<.45?p/.45*.746:.746+(p-.45)/.55*.254,[x,y]=mean(cells,rect)
  const limit=cells.length?Math.min(rect.w*.33,135):rect.w*.25,rx=limit*smooth(0,.30,q)*(1-smooth(.66,1,q)),ry=rx*.80
  ctx.save();ctx.translate(x,y);ctx.globalAlpha*=smooth(0,.12,q);glow(ctx,0,0,rx*1.65+1,'#713be5',.4)
  const g=ctx.createRadialGradient(0,0,0,0,0,rx+1);g.addColorStop(0,'#020007');g.addColorStop(.55,'#0a0519');g.addColorStop(.84,'#351358');g.addColorStop(1,'#8155d600');ctx.fillStyle=g;ctx.beginPath();ctx.ellipse(0,0,rx,ry,0,0,TAU);ctx.fill()
  for(let k=0;k<9;k++){ctx.beginPath();for(let j=0;j<85;j++){const u=j/84,a=k*TAU/9+u*5.5-p*10,r=rx*(1-u)*(.7+.3*rnd(k,seed)),x=Math.cos(a)*r,y=Math.sin(a)*r*.8;if(j)ctx.lineTo(x,y);else ctx.moveTo(x,y)}ctx.strokeStyle=k%3?'#9e67ff88':'#e2c5ffbb';ctx.lineWidth=k%3?2:4;ctx.shadowColor='#955fff';ctx.shadowBlur=12;ctx.stroke()}
  ctx.shadowBlur=0
  for(let i=0;i<90;i++){const a=TAU*rnd(i+65,seed)-p*8,q=(rnd(i,seed)+p*1.7)%1,r=rx*(1-q);ctx.fillStyle=i%4?'#a39ccd':'#e1c9ff';ctx.globalAlpha=smooth(0,.15,p)*(1-q)*.7;ctx.save();ctx.translate(Math.cos(a)*r,Math.sin(a)*r*.8);ctx.rotate(a);ctx.fillRect(0,0,2+rnd(i,3)*4,2+rnd(i,6)*7);ctx.restore()}
  ctx.restore();shock(ctx,x,y,(p-.45)*1.5,'#b193ff',310)
}
function splash(ctx: CanvasRenderingContext2D,p: number,rect: EffectRect,cells: readonly EffectCell[],seed: number,origin?: EffectPoint): void {
  // 调用端只传追加伤害的四邻格，中心只作为水压起点，避免重演中心伤害。
  if(!cells.length)return
  const [x,y]=origin??mean(cells,rect),age=(p-.45)*1.55;if(age<0||age>.85)return
  shock(ctx,x,y,age,'#c9f4ff',335);shock(ctx,x,y,age-.045,'#669dc9',280);particles(ctx,x,y,age,'#e8c69b',70,1.2,seed)
  for(let i=0;i<20;i++){const a=TAU*i/20,r=age*(110+rnd(i,seed)*130);ctx.save();ctx.globalAlpha*=Math.max(0,1-age/.65);line(ctx,[[x+Math.cos(a)*r*.65,y+Math.sin(a)*r*.5],[x+Math.cos(a)*r,y+Math.sin(a)*r*.7-age*18]],'#8ad6f4',2,2);ctx.restore()}
  for(const c of cells)glow(ctx,c.cx,c.cy,48,'#abddff',Math.max(0,1-Math.abs(age-.12)*8)*.6)
}
function seal(ctx: CanvasRenderingContext2D,p: number,rect: EffectRect): void {
  const fade=smooth(0,.12,p)*(1-smooth(.7,1,p)),close=smooth(0,.46,p),x=rect.x-17,y=rect.y-16,w=rect.w+34,h=rect.h+32
  ctx.save();ctx.globalAlpha*=fade
  const veil=ctx.createLinearGradient(x,y,x+w,y+h);veil.addColorStop(0,'#839bc83b');veil.addColorStop(.4,'#253c781c');veil.addColorStop(1,'#5e83bd55');ctx.fillStyle=veil
  ctx.beginPath();ctx.roundRect(x,y,w,h,12);ctx.fill();ctx.strokeStyle='#b7c8f4';ctx.lineWidth=1.4;ctx.shadowColor='#7196d4';ctx.shadowBlur=9;ctx.stroke();ctx.shadowBlur=0
  for(let k=0;k<7;k++){const xx=x+w*k/6;line(ctx,[[xx,y-36*(1-close)],[xx,y+close*h]],'#b4c9f04f',.8);if(k===0||k===6)line(ctx,[[xx-5,y],[xx-5,y+h]],'#8facdb9c',1.8,7)}
  for(const sign of [-1,1]){const yy=y+h/2+sign*h/2*close;line(ctx,[[x-11,yy],[x+w+11,yy]],'#d4e0ff',2,9);for(let j=0;j<8;j++){const xx=x+w*(j+.5)/8;line(ctx,[[xx-5,yy-sign*7],[xx,yy+sign*2],[xx+5,yy-sign*7]],'#e0e6ffbb',1.1)}}
  const a=Math.max(0,p-.45);if(a<.35){ctx.globalAlpha*=1-a/.35;ctx.beginPath();ctx.roundRect(x-18*a,y-18*a,w+36*a,h+36*a,12);ctx.strokeStyle='#c4d4ff';ctx.lineWidth=1.3;ctx.stroke()}
  ctx.restore()
}

/** 连锁反制直接绑定当前正在结算的卡面矩形。不要传右侧连锁记录栏。 */
export function drawCounterEffect(ctx: CanvasRenderingContext2D,kind: 'negate'|'gabriel',progress: number,cardRect: EffectRect): void {
  if(!validRect(cardRect)||!Number.isFinite(progress)||progress<=0||progress>=1)return
  const p=clamp(progress),unit=cardRect.w/300,[x,y]=center(cardRect)
  ctx.save();ctx.translate(x,y);ctx.scale(unit,unit);ctx.globalAlpha*=1-smooth(.7,1,p);ctx.lineCap='round';ctx.lineJoin='round'
  if(kind==='negate'){
    const q=smooth(.04,.30,p),sx=-185,sy=205,ex=190,ey=-210
    ctx.save();ctx.globalCompositeOperation='screen';line(ctx,[[sx,sy],[mix(sx,ex,q),mix(sy,ey,q)]],'#9ddcf1',10,23);line(ctx,[[sx,sy],[mix(sx,ex,q),mix(sy,ey,q)]],'#f3ffff',2.3);ctx.restore()
    if(p>.30){const age=p-.30;particles(ctx,0,0,age,'#b8dff1',75,1,63);for(let j=0;j<7;j++){const q=(j-3)*43;line(ctx,[[q-15,-q+30],[q+10,-q-15]],'#9ec6df99',.8)}}
  }else{
    const q=smooth(.02,.48,p),sy=-cardRect.h/unit*.80,yy=mix(sy,0,q)
    ctx.save();ctx.globalCompositeOperation='screen';const g=ctx.createLinearGradient(-48,0,48,0);g.addColorStop(0,'#e3c07100');g.addColorStop(.40,'#f6da9799');g.addColorStop(.50,'#fff8dc');g.addColorStop(.60,'#f6da9799');g.addColorStop(1,'#e3c07100');ctx.fillStyle=g;ctx.fillRect(-48,sy,96,yy-sy);line(ctx,[[0,sy],[0,yy]],'#fff9df',4,28);ellipse(ctx,0,0,165*smooth(.30,.55,p),42*smooth(.30,.55,p),'#f4dfa9b0',1.2);ctx.restore()
    if(p>.48){glow(ctx,0,0,190,'#ffe8ab',Math.exp(-(p-.48)*13)*.6);particles(ctx,0,0,p-.48,'#f9e6b7',90,1,72)}
  }
  ctx.restore()
}

/** 主体动效在 progress≈0.45 触地；不绘 UI、卡面或修改任何游戏状态。 */
export function drawCardEffect(ctx: CanvasRenderingContext2D,frame: CardEffectFrame,geometry: CardEffectGeometry): void {
  if(!Number.isFinite(frame.progress)||frame.progress<=0||frame.progress>=1||!validRect(geometry.targetBoard))return
  if(frame.kind==='negate'||frame.kind==='gabriel')return
  const p=clamp(frame.progress),seed=frame.seed??42,unit=geometry.targetBoard.w/420
  const rect=normalizeRect(geometry.targetBoard,unit),source=normalizeRect(geometry.sourceBoard??geometry.targetBoard,unit)
  const cells=(geometry.cells??[]).filter(c=>validRect(c)&&Number.isFinite(c.cx)&&Number.isFinite(c.cy)).map(c=>normalizeCell(c,unit))
  // 隐私授权在绘制边界再次检查，公开区域参数不能意外成为复活落点。
  const privateCells=frame.privateTargets===true?(geometry.privateCells??[]).filter(c=>validRect(c)&&Number.isFinite(c.cx)&&Number.isFinite(c.cy)).map(c=>normalizeCell(c,unit)):[]
  ctx.save();ctx.scale(unit,unit);ctx.lineCap='round';ctx.lineJoin='round'
  switch(frame.kind){
    case 'bomb':bomb(ctx,p,source,rect,cells,seed);break
    case 'vortex':vortex(ctx,p,rect,cells,seed);break
    case 'fire':case 'ice':drawElements(ctx,frame.kind,p,cells,seed);break
    case 'splash':splash(ctx,p,rect,cells,seed,geometry.origin?[geometry.origin[0]/unit,geometry.origin[1]/unit]:undefined);break
    case 'seal':seal(ctx,p,rect);break
    case 'sanctuary':drawRecovery(ctx,'sanctuary',p,normalizeRect(geometry.boardsUnion??geometry.targetBoard,unit),[],seed);break
    case 'revive':case 'heal':case 'last_chance':case 'shield':drawRecovery(ctx,frame.kind,p,rect,privateCells,seed);break
  }
  ctx.restore()
}
export function clearCardEffectCaches(): void { clearElementCaches() }
export function warmCardEffectCaches(): void { warmElementCaches() }
