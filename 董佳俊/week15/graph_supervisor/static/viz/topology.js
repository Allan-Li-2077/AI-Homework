/* =============================================================================
 *  topology.js —— 拓扑可视化（辅助代码，非教学重点）· 深色科技感
 * =============================================================================
 *  与旧项目（market_research_subagents）的核心差异：
 *  旧项目：LLM 自主路由 → dispatch 事件到达时才生长节点（星形，图后知）
 *  本项目：确定性路由 → plan 事件一次预画整张 DAG（含依赖边，图先知）
 *  vanillar JS + SVG，零依赖。
 * =========================================================================== */
class TopoViz {
  constructor(host) {
    this.host = host;
    this.host.innerHTML = '';          // ← 切换问题整体换图，不堆叠
    this.svgNS = 'http://www.w3.org/2000/svg';
    this.nodes = {};                   // id -> {x, y, r, shape, status, g, c, label}
    this._clickCb = null;
    this.W = 380; this.H = 520;
    this.mainXY = { x: this.W / 2, y: 44 };
    this.svg = this._svg();
    this.host.appendChild(this.svg);
    const defs = document.createElementNS(this.svgNS, 'defs');
    defs.innerHTML = `
      <filter id="glow" x="-60%" y="-60%" width="220%" height="220%">
        <feGaussianBlur stdDeviation="3.5" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
      </filter>
      <marker id="arr-disp" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="6" markerHeight="6" orient="auto">
        <path d="M0,0 L8,4 L0,8 z" fill="#00d4ff"/></marker>
      <marker id="arr-dep" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="6" markerHeight="6" orient="auto">
        <path d="M0,0 L8,4 L0,8 z" fill="#ffb020"/></marker>
      <marker id="arr-ret" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="5" markerHeight="5" orient="auto">
        <path d="M0,0 L8,4 L0,8 z" fill="#5a6b8f"/></marker>`;
    this.svg.appendChild(defs);
  }

  _svg() {
    const s = document.createElementNS(this.svgNS, 'svg');
    s.setAttribute('viewBox', `0 0 ${this.W} ${this.H}`);
    s.setAttribute('width', '100%');
    s.setAttribute('style', 'background:radial-gradient(circle at 50% 30%, #142042 0%, #070b16 80%);border-radius:8px');
    return s;
  }

  _drawShape(x, y, r, shape, fill, stroke) {
    const el = document.createElementNS(this.svgNS, shape === 'rect' ? 'rect' : 'circle');
    if (shape === 'rect') {
      el.setAttribute('x', x - r); el.setAttribute('y', y - r * 0.7);
      el.setAttribute('width', r * 2); el.setAttribute('height', r * 1.4);
      el.setAttribute('rx', 5);
    } else {
      el.setAttribute('cx', x); el.setAttribute('cy', y); el.setAttribute('r', r);
    }
    el.setAttribute('fill', fill);
    el.setAttribute('stroke', stroke || '#00d4ff');
    el.setAttribute('stroke-width', '2');
    el.setAttribute('filter', 'url(#glow)');
    el.style.transition = 'all .3s';
    return el;
  }

  addNode(id, label, color, shape, x, y) {
    const r = shape === 'rect' ? 16 : 14;
    const g = document.createElementNS(this.svgNS, 'g');
    g.style.cursor = 'pointer';
    const c = this._drawShape(x, y, r, shape, '#0a2a5e', color);
    const t = document.createElementNS(this.svgNS, 'text');
    t.setAttribute('x', x); t.setAttribute('y', y + r + 13);
    t.setAttribute('text-anchor', 'middle'); t.setAttribute('font-size', '8.5');
    t.setAttribute('fill', '#8aa6d0');
    t.textContent = label.length > 9 ? label.slice(0, 9) + '…' : label;
    g.appendChild(c); g.appendChild(t);
    if (id) g.addEventListener('click', () => this._clickCb && this._clickCb(id));
    this.svg.appendChild(g);
    this.nodes[id] = { g, c, t, x, y, r, shape, color, status: 'idle', _pulse: null };
  }

  _edgePoints(f, t) {
    const a = this.nodes[f], b = this.nodes[t];
    const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
    return [a.x + dx / len * (a.r + 3), a.y + dy / len * (a.r + 3),
            b.x - dx / len * (b.r + 5), b.y - dy / len * (b.r + 5)];
  }

  addEdge(from, to, kind) {
    const [x1, y1, x2, y2] = this._edgePoints(from, to);
    const ln = document.createElementNS(this.svgNS, 'line');
    ln.setAttribute('x1', x1); ln.setAttribute('y1', y1);
    ln.setAttribute('x2', x2); ln.setAttribute('y2', y2);
    const style = kind === 'dispatch' ? ['#1f6a8f', 'url(#arr-disp)']
                 : kind === 'dependency' ? ['#8a5a1f', 'url(#arr-dep)']
                 : ['#2a3a5c', 'url(#arr-ret)'];
    ln.setAttribute('stroke', style[0]);
    ln.setAttribute('stroke-width', kind === 'dependency' ? '1.8' : '1.5');
    ln.setAttribute('stroke-dasharray', kind === 'return' ? '3 4' : '');
    ln.setAttribute('marker-end', style[1]);
    this.svg.appendChild(ln);
    return ln;
  }

  /* 确定性路由 → plan 事件时整张图已知，一次预画（含依赖边） */
  buildFromPlan(plan) {
    plan.stages.forEach((stage, i) => {
      const y = 150 + i * 120;
      const k = stage.length;
      stage.forEach((node, j) => {
        const x = k === 1 ? this.W / 2 : this.W / (k + 1) * (j + 1);
        this.addNode(node.node_id, node.label, node.color, node.shape, x, y);
      });
    });
    plan.edges.forEach(([f, t, kind]) => this.addEdge(f, t, kind));
  }

  setMain() {
    this.addNode('supervisor', '主 agent (Supervisor)', '#00d4ff', 'circle',
                 this.mainXY.x, this.mainXY.y);
  }

  markRunning(id) {
    const s = this.nodes[id]; if (!s) return;
    s.status = 'running';
    s.c.setAttribute('stroke', '#ffb020'); s.c.setAttribute('stroke-width', '3.5');
    s.c.setAttribute('fill', '#3a2a00');
    if (!s._pulse) {
      s._pulse = setInterval(() => {
        if (s.status !== 'running') { clearInterval(s._pulse); s._pulse = null; return; }
        if (s.shape === 'rect') {
          s.c.setAttribute('stroke-width', s.c.getAttribute('stroke-width') === '3.5' ? '5' : '3.5');
        } else {
          s.c.setAttribute('r', s.c.getAttribute('r') === '16' ? '13' : '16');
        }
      }, 450);
    }
  }

  markDone(id) {
    const s = this.nodes[id]; if (!s) return;
    s.status = 'done';
    if (s._pulse) { clearInterval(s._pulse); s._pulse = null; }
    s.c.setAttribute('fill', '#0d3d2a'); s.c.setAttribute('stroke', '#2ee6a0');
    s.c.setAttribute('stroke-width', '2.5');
    if (s.shape !== 'rect') s.c.setAttribute('r', '14');
  }

  reset() {
    Object.values(this.nodes).forEach(s => { if (s._pulse) clearInterval(s._pulse); });
    this.host.innerHTML = '';
    this.nodes = {};
  }

  onClick(cb) { this._clickCb = cb; }
}
