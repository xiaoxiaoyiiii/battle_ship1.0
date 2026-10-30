import type { EffectCell, EffectPoint } from './types'

function context(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const ctx=canvas.getContext('2d')
  if (!ctx) throw new Error('浏览器不支持 Canvas 2D')
  return ctx
}
let scratch: HTMLCanvasElement | undefined
function scratchCanvas(w: number,h: number): HTMLCanvasElement {
  if (!scratch) scratch=document.createElement('canvas')
  if (scratch.width!==w) scratch.width=w
  if (scratch.height!==h) scratch.height=h
  return scratch
}
  const TAU=Math.PI*2, clamp=(x: number,a=0,b=1)=>Math.max(a,Math.min(b,x));
  const smooth=(a: number,b: number,x: number)=>{x=clamp((x-a)/(b-a));return x*x*(3-2*x)};
  const hash=(n: number)=>{const x=Math.sin(n*127.1+311.7)*43758.5453123;return x-Math.floor(x)};
  function lattice(x: number,y: number,seed: number): number {
    let h=(Math.imul(x,374761393)+Math.imul(y,668265263)+Math.imul(seed,1442695041))|0
    h=Math.imul(h^(h>>>13),1274126177)
    return ((h^(h>>>16))>>>0)/4294967296
  }
  // 整数格点散列避免纹理生成阶段对每像素反复求 sin，保留同样的多层流噪声。
  function noise(x: number,y: number,s=0){const ix=Math.floor(x),iy=Math.floor(y),u=smooth(0,1,x-ix),v=smooth(0,1,y-iy),seed=Math.round(s*100);const a=lattice(ix,iy,seed),b=lattice(ix+1,iy,seed),c=lattice(ix,iy+1,seed),d=lattice(ix+1,iy+1,seed);return (a*(1-u)+b*u)*(1-v)+(c*(1-u)+d*u)*v}
  function fbm(x: number,y: number,s=0){return noise(x,y,s)*.57+noise(x*2.17,y*2.17,s+3)*.28+noise(x*4.77,y*4.77,s+7)*.15}
  function canvas(w: number,h: number){const c=document.createElement('canvas');c.width=w;c.height=h;return c}
  function radial(ctx: CanvasRenderingContext2D,x: number,y: number,r: number,color: string,a: number){if(a<=0||r<=0)return;const g=ctx.createRadialGradient(x,y,0,x,y,r);g.addColorStop(0,`rgba(${color},${a})`);g.addColorStop(.4,`rgba(${color},${a*.42})`);g.addColorStop(1,`rgba(${color},0)`);ctx.fillStyle=g;ctx.fillRect(x-r,y-r,r*2,r*2)}
  const iceAtlas=new Map<number, HTMLCanvasElement>();
  function iceTexture(seed: number){
    const key=Math.round(seed);const cached=iceAtlas.get(key);if(cached)return cached;
    const c=canvas(248,248),g=context(c),im=g.createImageData(248,248);
    for(let y=0;y<248;y++)for(let x=0;x<248;x++){
      const n=fbm(x/37,y/37,seed),f=noise(x/3.1,y/3.1,seed+17);
      const vein=Math.pow(clamp(1-Math.abs(n-.49)*10),8),polish=clamp((x+y)/496);
      const edge=1-smooth(0,20,Math.min(x,y,247-x,247-y));
      const frost=Math.pow(f,4)*edge;
      const i=(y*248+x)*4;im.data[i]=128+n*54+frost*50;im.data[i+1]=177+n*46+frost*24;im.data[i+2]=204+n*40;
      im.data[i+3]=clamp(.10+vein*.15+frost*.52+(1-polish)*.045)*255;
    }
    g.putImageData(im,0,0);if(iceAtlas.size>=4)iceAtlas.delete(iceAtlas.keys().next().value!);iceAtlas.set(key,c);return c;
  }
  interface FireTexture { image: HTMLCanvasElement; x: number; y: number; w: number; h: number }
  const flowAtlas=new Map<string, FireTexture>();
  let cachedFlowPixels=0;
  const MAX_FLOW_PIXELS=4_000_000;
  function fireFlow(frame: number,cells: readonly EffectCell[],seed: number){
    const b=bounds(cells),pad=24,top=94,scale=2.6,w=Math.ceil((b.r-b.x+pad*2)/scale),h=Math.ceil((b.b-b.y+top+24)/scale);
    const key=seed+':'+frame+':'+cells.map(c=>[c.x,c.y,c.w,c.h].join(',')).join('|');const cached=flowAtlas.get(key);if(cached)return cached;
    const c=canvas(w,h),g=context(c),im=g.createImageData(w,h),time=frame/45;
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      const wx=b.x-pad+x*scale,wy=b.y-top+y*scale;
      const n=fbm(wx/33+time*.58,wy/30-time*3.8,seed),fine=noise(wx/9-time,wy/10-time*7.4,seed+7),warp=(n-.5)*30;
      let field=0,smoke=0;
      for(let j=0;j<cells.length;j++){
        const cell=cells[j],height=58+hash(seed+j*17)*33;
        const v=(cell.cy+20-wy)/height,u=(wx-cell.cx+warp)/48;
        if(v>-.12&&v<1.4){
          const crown=.73+(noise(wx/24+time*.4,j*3+time*3.1,seed+11)-.5)*.7;
          const spread=.88-.27*clamp(v);
          const body=Math.exp(-u*u/(spread*spread)*2.5)*smooth(crown+.17,crown-.07,v)*smooth(-.12,.04,v);
          const ignition=smooth(j*.026+.025,j*.026+.145,frame/50.4);
          field+=body*(.81+fine*.19)*ignition;
          const sv=(cell.cy-24-wy)/(height*1.3),su=(wx-cell.cx+warp*1.3)/58;
          if(sv>0)smoke+=Math.exp(-su*su*1.8)*smooth(1.25,.25,sv)*smooth(0,.25,sv)*n*.35;
        }
      }
      field=clamp(field);const a=smooth(.035,.32,field),hot=clamp(field*.81+(n-.5)*.5+fine*.09);
      let r=0,gc=0,bl=0;
      if(hot<.3){const q=hot/.3;r=78+q*89;gc=24+q*29;bl=14+q*5}
      else if(hot<.69){const q=(hot-.3)/.39;r=167+q*79;gc=53+q*101;bl=19+q*26}
      else {const q=(hot-.69)/.31;r=246+q*9;gc=154+q*89;bl=45+q*141}
      const sa=clamp(smoke)*.44,aa=a*.96,oa=aa+sa*(1-aa),i=(y*w+x)*4;
      im.data[i]=(r*aa+37*sa*(1-aa))/(oa||1);im.data[i+1]=(gc*aa+33*sa*(1-aa))/(oa||1);im.data[i+2]=(bl*aa+36*sa*(1-aa))/(oa||1);im.data[i+3]=oa*255;
    }
    g.putImageData(im,0,0);const result={image:c,x:b.x-pad,y:b.y-top,w:w*scale,h:h*scale};while(cachedFlowPixels+w*h>MAX_FLOW_PIXELS&&flowAtlas.size){const key=flowAtlas.keys().next().value!;const old=flowAtlas.get(key)!;cachedFlowPixels-=old.image.width*old.image.height;flowAtlas.delete(key);}flowAtlas.set(key,result);cachedFlowPixels+=w*h;return result;
  }
  function bounds(cells: readonly EffectCell[]){return {x:Math.min(...cells.map(c=>c.x)),y:Math.min(...cells.map(c=>c.y)),r:Math.max(...cells.map(c=>c.x+c.w)),b:Math.max(...cells.map(c=>c.y+c.h))}}
  function clipCells(ctx: CanvasRenderingContext2D,cells: readonly EffectCell[],pad=0){ctx.beginPath();for(const c of cells)ctx.rect(c.x-pad,c.y-pad,c.w+pad*2,c.h+pad*2);ctx.clip()}
  function line(ctx: CanvasRenderingContext2D,pts: readonly EffectPoint[],color: string,width: number){if(pts.length<2)return;ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(...pts[0]);for(let i=1;i<pts.length;i++)ctx.lineTo(...pts[i]);ctx.stroke()}
  function fire(ctx: CanvasRenderingContext2D,p: number,cells: readonly EffectCell[],seed: number){
    const fade=1-smooth(.71,1,p),rise=smooth(.02,.25,p);if(fade<=0||rise<=0)return;
    const contact=Math.exp(-Math.pow((p-.43)/.05,2));
    ctx.save();ctx.globalCompositeOperation='source-over';
    /* 烟层使用低饱和灰褐色，托住明亮火核，避免泛白的霓虹光团。 */
    for(let j=0;j<cells.length;j++){
      const c=cells[j],delay=j*.027,local=clamp((p-delay)/.9),strength=smooth(.02,.15,local)*fade;
      for(let k=0;k<5;k++){
        const h=hash(seed+j*19+k*3),drift=(p*1.4+k*.177)%1;
        radial(ctx,c.cx+(h-.5)*c.w*.8+Math.sin(p*5+k)*8,c.cy-12-drift*87,c.w*(.28+drift*.42),'34,31,35',strength*.17*(1-drift));
      }
    }
    /* 连通格间的灼热流动，只沿公开选择区域，不查询船的位置。 */
    ctx.save();clipCells(ctx,cells,3);ctx.globalCompositeOperation='screen';
    for(let j=0;j<cells.length;j++){
      const c=cells[j],heat=smooth(j*.028,j*.028+.14,p)*fade;
      radial(ctx,c.cx,c.cy+13,c.w*.65,'229,66,18',heat*.3);
      radial(ctx,c.cx,c.cy+15,c.w*.31,'255,183,87',heat*.21+contact*.34);
      for(let k=0;k<8;k++){
        const z=hash(seed+j*31+k),a=z*TAU,r=c.w*(.08+hash(k+seed)*.3);
        const x=c.cx+Math.cos(a)*r,y=c.cy+12+Math.sin(a)*r*.32;
        ctx.fillStyle=`rgba(255,${120+Math.floor(z*65)},60,${heat*(.22+.2*hash(k*8))})`;ctx.fillRect(x,y,1.2+z*2,.6);
      }
    }
    ctx.restore();
    /* 一张连续的噪声火场把相邻热源合为流动火墙，避免六枚贴纸状火苗。 */
    const phase=p*1.8*28,frame=Math.floor(phase),blend=phase-frame,flow=fireFlow(frame,cells,seed),next=fireFlow(frame+1,cells,seed);
    const mixed=scratchCanvas(flow.image.width,flow.image.height),mc=context(mixed);mc.clearRect(0,0,mixed.width,mixed.height);mc.globalCompositeOperation="source-over";mc.globalAlpha=1-blend;mc.drawImage(flow.image,0,0);mc.globalCompositeOperation='lighter';mc.globalAlpha=blend;mc.drawImage(next.image,0,0);
    ctx.save();ctx.globalAlpha=fade*rise*.96;ctx.drawImage(mixed,flow.x,flow.y,flow.w,flow.h);ctx.restore();
    for(let j=0;j<cells.length;j++){
      const c=cells[j],delay=j*.027,local=clamp((p-delay)/.9),strength=smooth(.02,.17,local)*fade;
      for(let k=0;k<9;k++){
        const q=(p*1.3+hash(seed+j*17+k*3))%1,life=Math.sin(q*Math.PI)*strength;
        const xx=c.cx+(hash(j*27+k+seed)-.5)*c.w+Math.sin(q*5+k)*7,yy=c.cy+8-q*(58+hash(k+j)*69);
        ctx.strokeStyle=`rgba(255,${145+Math.floor(hash(k)*72)},91,${life*.83})`;ctx.lineWidth=k%3===0?1.3:.65;
        ctx.beginPath();ctx.moveTo(xx,yy);ctx.lineTo(xx-1.1,yy+2+q*3);ctx.stroke();
      }
    }
    ctx.restore();
  }
  function ice(ctx: CanvasRenderingContext2D,p: number,cells: readonly EffectCell[],seed: number){
    const b=bounds(cells),w=b.r-b.x,h=b.b-b.y,cx=b.x+w*.49,cy=b.y+h*.50;
    const grow=smooth(.025,.43,p),fade=1-smooth(.74,1,p),pulse=Math.exp(-Math.pow((p-.43)/.032,2));if(grow<=0||fade<=0)return;
    ctx.save();clipCells(ctx,cells,2);
    /* 冰膜以不规则的冻结前沿扩散，仍然能看见棋盘变化。 */
    const radius=Math.hypot(w,h)*.54*grow;
    const mask=scratchCanvas(Math.ceil(w+6),Math.ceil(h+6)),mg=context(mask);mg.clearRect(0,0,mask.width,mask.height);mg.globalCompositeOperation="source-over";
    mg.drawImage(iceTexture(42),0,0,mask.width,mask.height);
    mg.globalCompositeOperation='destination-in';
    const g=mg.createRadialGradient(w*.49,h*.5,Math.max(0,radius-17),w*.49,h*.5,radius+3);g.addColorStop(0,'rgba(255,255,255,1)');g.addColorStop(1,'rgba(255,255,255,0)');mg.fillStyle=g;mg.fillRect(0,0,mask.width,mask.height);
    ctx.globalAlpha=fade*(.86+pulse*.14);ctx.drawImage(mask,b.x-3,b.y-3);
    /* 每条裂纹有不同分支、长度和速度，没有格子复制的放射图案。 */
    for(let j=0;j<10;j++){
      const a=(j/10)*TAU+(hash(seed+j)-.5)*.28,len=(.38+hash(j+seed+5)*.19)*Math.min(w,h),pts: EffectPoint[]=[[cx,cy]];
      let x=cx,y=cy;
      const n=10;for(let k=1;k<=n;k++){
        const d=a+(hash(seed+j*43+k)-.5)*.65;
        x+=Math.cos(d)*len/n;y+=Math.sin(d)*len/n;pts.push([x,y]);
      }
      const count=Math.max(1,Math.min(pts.length,Math.floor(grow*(pts.length+2)-hash(j)*2)));
      const visible=pts.slice(0,count);
      line(ctx,visible,`rgba(12,46,64,${fade*.40})`,2.6);
      line(ctx,visible.map(([x,y]): EffectPoint=>[x-.5,y-.5]),`rgba(213,242,249,${fade*(.31+pulse*.24)})`,.8);
      for(let k=3;k<count;k+=3){
        const [px,py]=pts[k],ang=a+(k%2?-.88:.78),ll=(9+hash(j*8+k)*14)*grow;
        const branch: EffectPoint[]=[[px,py],[px+Math.cos(ang)*ll*.57,py+Math.sin(ang)*ll*.57],[px+Math.cos(ang+.25)*ll,py+Math.sin(ang+.25)*ll]];
        line(ctx,branch,`rgba(209,237,247,${fade*.3})`,.55);
      }
    }
    /* 周边微细霜枝；只勾区域边缘，绝不沿隐藏船描边。 */
    const edges=[[b.x,b.y,b.r,b.y],[b.r,b.y,b.r,b.b],[b.r,b.b,b.x,b.b],[b.x,b.b,b.x,b.y]];
    for(let side=0;side<4;side++)for(let j=0;j<31;j++){
      const [x1,y1,x2,y2]=edges[side],t=(j+.3+hash(j*8+seed)*.4)/31;
      const x=x1+(x2-x1)*t,y=y1+(y2-y1)*t,ang=side* Math.PI/2+Math.PI/2;
      const dist=Math.hypot(x-cx,y-cy),on=smooth(dist-18,dist+5,radius)*fade;
      if(on<=0)continue;
      const ll=3+hash(seed+side*73+j)*11;
      ctx.strokeStyle=`rgba(214,240,249,${on*.54})`;ctx.lineWidth=.7;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+Math.cos(ang)*ll,y+Math.sin(ang)*ll);
      for(let k=1;k<=3;k++){const q=k/4,fx=x+Math.cos(ang)*ll*q,fy=y+Math.sin(ang)*ll*q;for(const sign of [-1,1]){ctx.moveTo(fx,fy);ctx.lineTo(fx+Math.cos(ang+sign*.9)*ll*(1-q)*.45,fy+Math.sin(ang+sign*.9)*ll*(1-q)*.45)}}ctx.stroke();
    }
    /* 斜掠反光是短促的冷色高光，不用大几何冰块盖住棋盘。 */
    const sweep=-w+p*4.5*w;
    const sg=ctx.createLinearGradient(b.x+sweep,b.y,b.x+sweep+w*.26,b.b);sg.addColorStop(0,'rgba(225,246,250,0)');sg.addColorStop(.49,`rgba(225,246,250,${fade*grow*.13})`);sg.addColorStop(.53,`rgba(239,251,255,${fade*grow*.29})`);sg.addColorStop(1,'rgba(225,246,250,0)');ctx.fillStyle=sg;ctx.fillRect(b.x,b.y,w,h);
    ctx.restore();
    /* 冻结触地的薄雾只在范围边缘，留下透明的落点。 */
    ctx.save();ctx.globalCompositeOperation='screen';
    for(let j=0;j<12;j++){const q=hash(seed+j*9),a=q*TAU,r=Math.min(w,h)*.5*grow;radial(ctx,cx+Math.cos(a)*r,cy+Math.sin(a)*r,12+hash(j)*10,'154,196,218',fade*.12*smooth(.08,.28,p));}
    if(pulse>.01){ctx.strokeStyle=`rgba(221,246,255,${pulse*.62})`;ctx.lineWidth=1;ctx.beginPath();ctx.ellipse(cx,cy,w*.48,h*.48,0,0,TAU);ctx.stroke();}
    ctx.restore();
  }

/** 缓存按像素预算限制；退出对局时调用释放。 */
export function clearElementCaches(): void { iceAtlas.clear();flowAtlas.clear();cachedFlowPixels=0;scratch=undefined }
/** 可在进入战斗或卡面入场前预热一次，主体播放期间只复用冰膜。 */
export function warmElementCaches(): void { iceTexture(42) }
export function elementCacheStats(): { flowPixels: number; flowFrames: number; iceTextures: number } { return { flowPixels: cachedFlowPixels, flowFrames: flowAtlas.size, iceTextures: iceAtlas.size } }
export function drawElements(ctx: CanvasRenderingContext2D,kind: 'fire' | 'ice',p: number,cells: readonly EffectCell[],seed=42): void {
  if(!cells.length||p<=0||p>=1)return
  ctx.save();ctx.lineCap='round';ctx.lineJoin='round'
  if(kind==='fire')fire(ctx,p,cells,seed);else ice(ctx,p,cells,seed)
  ctx.restore()
}
