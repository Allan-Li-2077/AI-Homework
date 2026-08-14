/**
 * SVG 拓扑可视化（vanilla JS 无依赖）
 * 主节点 + dispatch 时动态加入子客服节点 + 主→子边
 * 节点可脉冲（运行中）、变绿（完成）
 */
class TopoViz {
  constructor(container) {
    this.container = container;
    this.container.innerHTML = '';
    const w = container.clientWidth || 400;
    const h = container.clientHeight || 240;
    this.svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.svg.setAttribute('width', w);
    this.svg.setAttribute('height', h);
    this.svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    this.svg.style.background = 'radial-gradient(circle at 30% 30%, rgba(79,140,255,0.08), transparent 60%)';
    this.container.appendChild(this.svg);

    // defs: 发光滤镜
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
    defs.innerHTML = `
      <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
        <feGaussianBlur stdDeviation="3" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>`;
    this.svg.appendChild(defs);

    this.nodes = {};      // id -> {x,y,r,color,label,el,ringEl}
    this.edges = [];      // [{from,to,el}]
    this.pulseTimers = {};
  }

  _ns(tag) {
    return document.createElementNS('http://www.w3.org/2000/svg', tag);
  }

  addNode(id, label, color, isMain = false) {
    if (this.nodes[id]) return;
    const w = +this.svg.getAttribute('width');
    const h = +this.svg.getAttribute('height');
    const x = isMain ? w * 0.18 : w * 0.65 + (Math.random() - 0.5) * 60;
    const y = isMain ? h * 0.5 : 40 + Object.keys(this.nodes).length * 50 % h;

    const g = this._ns('g');
    g.setAttribute('transform', `translate(${x},${y})`);

    // 外环（脉冲用）
    const ring = this._ns('circle');
    ring.setAttribute('r', 26);
    ring.setAttribute('fill', 'none');
    ring.setAttribute('stroke', color);
    ring.setAttribute('stroke-width', 1.5);
    ring.setAttribute('opacity', 0.3);
    g.appendChild(ring);

    // 节点圆
    const c = this._ns('circle');
    c.setAttribute('r', 20);
    c.setAttribute('fill', color);
    c.setAttribute('filter', 'url(#glow)');
    c.setAttribute('opacity', 0.85);
    g.appendChild(c);

    // 标签
    const t = this._ns('text');
    t.setAttribute('y', 40);
    t.setAttribute('text-anchor', 'middle');
    t.setAttribute('fill', '#e6ebff');
    t.setAttribute('font-size', 11);
    t.textContent = label;
    g.appendChild(t);

    this.svg.appendChild(g);
    this.nodes[id] = { x, y, color, label, el: g, ringEl: ring, done: false };
  }

  addEdge(from, to) {
    const a = this.nodes[from], b = this.nodes[to];
    if (!a || !b) return;
    const line = this._ns('line');
    line.setAttribute('x1', a.x);
    line.setAttribute('y1', a.y);
    line.setAttribute('x2', b.x);
    line.setAttribute('y2', b.y);
    line.setAttribute('stroke', b.color);
    line.setAttribute('stroke-width', 2);
    line.setAttribute('stroke-dasharray', '5,4');
    line.setAttribute('opacity', 0.6);
    this.svg.insertBefore(line, this.svg.firstChild);
    this.edges.push({ from, to, el: line });

    // 流光动画：stroke-dashoffset
    let off = 0;
    const anim = () => {
      off = (off - 0.5) % 9;
      line.setAttribute('stroke-dashoffset', off);
      if (!b.done) requestAnimationFrame(anim);
    };
    anim();
  }

  pulse(id, final = false) {
    const n = this.nodes[id];
    if (!n) return;
    if (this.pulseTimers[id]) clearInterval(this.pulseTimers[id]);
    if (final) {
      n.ringEl.setAttribute('r', 26);
      n.ringEl.setAttribute('opacity', 0);
      n.el.querySelector('circle:nth-of-type(2)').setAttribute('fill', '#3ad29f');
      return;
    }
    let r = 26, dir = 1;
    this.pulseTimers[id] = setInterval(() => {
      r += dir * 0.6;
      if (r > 32) dir = -1;
      if (r < 26) dir = 1;
      n.ringEl.setAttribute('r', r);
      n.ringEl.setAttribute('opacity', 0.3 + (32 - r) / 12);
    }, 40);
  }

  markDone(id) {
    const n = this.nodes[id];
    if (!n) return;
    n.done = true;
    if (this.pulseTimers[id]) clearInterval(this.pulseTimers[id]);
    n.ringEl.setAttribute('r', 26);
    n.ringEl.setAttribute('opacity', 0);
    n.el.querySelector('circle:nth-of-type(2)').setAttribute('fill', '#3ad29f');
  }
}
