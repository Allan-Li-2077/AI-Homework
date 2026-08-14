/* =============================================================================
 *  force_graph.js  ——  纯手写 force-directed 图可视化（辅助代码，非教学重点）
 * =============================================================================
 *  适配求职公司调研项目：7 种实体类型的配色。其余逻辑与原版一致。
 *
 *  用法（在 index.html 里）：
 *    const fg = new ForceGraph(document.getElementById('graphCanvas'));
 *    fg.setData(nodes, edges);   // nodes:[{uid,name,type}], edges:[{src,dst,rel}]
 *    fg.start();
 * =========================================================================== */
class ForceGraph {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.nodes = [];
    this.edges = [];
    this.raf = null;
    // ====== 以下颜色适配【求职场景】7 种实体类型 ======
    this.colors = {
      Company:           '#1E3A5F',   // 深蓝：公司本体
      BusinessSegment:   '#2E86AB',   // 蓝：业务板块
      SalaryIndicator:   '#D4720A',   // 橙：薪资指标
      TechnologyStack:   '#217B45',   // 绿：技术栈
      Person:            '#884EA0',   // 紫：核心人物
      Industry:          '#C0392B',   // 红：行业赛道
      InterviewProcess:  '#117A65',   // 青：面试流程
      default:           '#666'
    };
    this.legend = [
      ['Company 公司', this.colors.Company],
      ['BusinessSegment 业务', this.colors.BusinessSegment],
      ['SalaryIndicator 薪资', this.colors.SalaryIndicator],
      ['TechnologyStack 技术', this.colors.TechnologyStack],
      ['Person 人物', this.colors.Person],
      ['Industry 行业', this.colors.Industry],
      ['InterviewProcess 面试', this.colors.InterviewProcess],
    ];
    // 拖拽交互
    this.dragNode = null;
    canvas.addEventListener('mousedown', e => this._onDown(e));
    canvas.addEventListener('mousemove', e => this._onMove(e));
    canvas.addEventListener('mouseup', () => this.dragNode = null);
    canvas.addEventListener('mouseleave', () => this.dragNode = null);
  }

  setData(nodes, edges) {
    const w = this.canvas.width, h = this.canvas.height;
    this.nodes = nodes.map(n => ({
      ...n,
      x: w/2 + (Math.random()-0.5)*200,
      y: h/2 + (Math.random()-0.5)*200,
      vx: 0, vy: 0, r: 12
    }));
    // 边：兼容多种字段名（src/dst/src_uid/dst_uid/s/t）
    const byUid = {}, byName = {};
    this.nodes.forEach(n => { byUid[n.uid] = n; byName[n.name] = n; });
    this.edges = edges.map(e => {
      let a = byUid[e.src] || byUid[e.src_uid] || byUid[e.s] || byName[e.src];
      let b = byUid[e.dst] || byUid[e.dst_uid] || byUid[e.t] || byName[e.dst];
      return { a, b, rel: e.rel || e.type || e.relation || '' };
    }).filter(e => e.a && e.b);
  }

  _step() {
    // 简化版 force：节点间斥力 + 边弹簧 + 向中心收拢
    const k_rep = 2200, k_spring = 0.04, k_center = 0.006, len = 90;
    const cx = this.canvas.width/2, cy = this.canvas.height/2;
    // 斥力
    for (let i = 0; i < this.nodes.length; i++) {
      for (let j = i+1; j < this.nodes.length; j++) {
        const a = this.nodes[i], b = this.nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx*dx + dy*dy + 0.01;
        let f = k_rep / d2;
        let dn = Math.sqrt(d2);
        a.vx += (dx/dn) * f; a.vy += (dy/dn) * f;
        b.vx -= (dx/dn) * f; b.vy -= (dy/dn) * f;
      }
    }
    // 弹簧
    this.edges.forEach(e => {
      let dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
      let dn = Math.sqrt(dx*dx+dy*dy) + 0.01;
      let f = k_spring * (dn - len);
      e.a.vx += (dx/dn) * f; e.a.vy += (dy/dn) * f;
      e.b.vx -= (dx/dn) * f; e.b.vy -= (dy/dn) * f;
    });
    // 收拢 + 阻尼 + 移动
    this.nodes.forEach(n => {
      if (n === this.dragNode) return;
      n.vx += (cx - n.x) * k_center;
      n.vy += (cy - n.y) * k_center;
      n.vx *= 0.84; n.vy *= 0.84;
      n.x += n.vx; n.y += n.vy;
    });
    this._draw();
  }

  _draw() {
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    // 边 + 关系标签
    ctx.strokeStyle = '#bbb'; ctx.lineWidth = 1;
    ctx.font = '10px Calibri'; ctx.fillStyle = '#888';
    this.edges.forEach(e => {
      ctx.beginPath(); ctx.moveTo(e.a.x, e.a.y); ctx.lineTo(e.b.x, e.b.y); ctx.stroke();
      const mx = (e.a.x+e.b.x)/2, my = (e.a.y+e.b.y)/2;
      if (e.rel) ctx.fillText(e.rel, mx + 3, my - 2);
    });
    // 节点
    this.nodes.forEach(n => {
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, 2*Math.PI);
      ctx.fillStyle = this.colors[n.type] || this.colors.default;
      ctx.fill(); ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = '#222'; ctx.font = 'bold 11px "Microsoft YaHei",Calibri';
      ctx.textAlign = 'center';
      const label = (n.name||'').length > 9 ? n.name.slice(0,9)+'…' : (n.name||'');
      ctx.fillText(label, n.x, n.y + n.r + 13);
    });
    // 图例（左上角）
    ctx.save();
    let ly = 14;
    ctx.font = '12px "Microsoft YaHei",Calibri';
    this.legend.forEach(([name, color]) => {
      ctx.fillStyle = color; ctx.fillRect(10, ly-10, 12, 12);
      ctx.fillStyle = '#333'; ctx.textAlign = 'left';
      ctx.fillText(name, 28, ly);
      ly += 18;
    });
    ctx.restore();
  }

  _onDown(e) {
    const r = this.canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    this.dragNode = this.nodes.find(n => Math.hypot(n.x-mx, n.y-my) < n.r + 2) || null;
  }
  _onMove(e) {
    if (!this.dragNode) return;
    const r = this.canvas.getBoundingClientRect();
    this.dragNode.x = e.clientX - r.left;
    this.dragNode.y = e.clientY - r.top;
    this.dragNode.vx = 0; this.dragNode.vy = 0;
  }

  start() { this._loop(); }
  _loop() { this._step(); this.raf = requestAnimationFrame(() => this._loop()); }
  stop() { if (this.raf) cancelAnimationFrame(this.raf); }
  clear() { this.stop(); this.ctx.clearRect(0,0,this.canvas.width,this.canvas.height); this.nodes=[]; this.edges=[]; }
}
