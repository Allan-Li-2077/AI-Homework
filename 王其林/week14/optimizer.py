"""
进化 Agent（Skill 优化器）：分析失败样本与当前 Skill，产出并执行最小必要的 Skill
操作，让 Skill 自动迭代（对齐 self_evolving_agent 的 BackgroundReviewer，动作类型
为 rewrite / patch / create）。

进化策略（参考 self_evolving_agent/background_reviewer.py 核心原则）：
  1. 仅修复观察到的失败：只针对样本里出现的问题类型做改动，不扩展到未出现的场景
  2. 最小改动优先——patch 优先：能在已有 Skill 追加/改一条分支解决的，不 rewrite 整份；
     patch 的 old_text 只含要改的那几行，逐字复制
  3. 聚焦核心 + 类内完整：按失败条数从高到低，**尽量覆盖所有失败类别**——梯度由新题维持，
     不需要刻意限制修复类别数；但每一类须补充完整：同一诗人的全部名篇、同一诗派的全部代表、
     同一知识分支的全部术语

双模式：
  - fix（有失败）：patch 优先修复 1~2 类失败；仅当当前 Skill 完全为空（<60 tokens）才允许 rewrite
  - refine（零失败）：token>1000 时 rewrite 压缩（必须下降≥10% 否则跳过）；token≤1000 时 patch 扩展
"""

import os
import re
import json
from openai import OpenAI

import tiktoken

ENC = tiktoken.get_encoding("cl100k_base")

# 信息完整性核对表：rewrite（压缩）时必须保留这些知识实体（古诗词知识图谱核心知识点）
INFO_CHECKLIST = [
    "诗体体制：古体诗（不拘格律）、近体诗（格律诗）；近体诗分绝句（四句，律绝/古绝）与律诗（八句，颔联/颈联必须对仗）",
    "词的体制：词牌（曲调名）、上阕/下阕、长短句（词的别称）、诗余",
    "散曲：包括小令与套数两种体制；曲牌为曲的曲调名",
    "唐代诗人字号：李白（字太白，号青莲居士，人称谪仙）、杜甫（字子美，自号少陵野老，尊称诗圣）、白居易（字乐天，号香山居士）、王维（字摩诘，尊称诗佛）",
    "唐诗名篇名句：静夜思（床前明月光/低头思故乡）、将进酒（君不见，黄河之水天上来）、蜀道难（蜀道之难，难于上青天）、春望（国破山河在/城春草木深）、茅屋为秋风所破歌（安得广厦千万间/大庇天下寒士）、长恨歌（在天愿作比翼鸟/在地愿为连理枝）、琵琶行（同是天涯沦落人/相逢何必曾相识）",
    "王维名篇与评价：相思（红豆生南国/春来发几枝）；苏轼评王维「诗中有画，画中有诗」；属山水田园诗派",
    "名句集锦：登鹳雀楼（白日依山尽/黄河入海流/欲穷千里目/更上一层楼）、春晓（春眠不觉晓/处处闻啼鸟）、出塞（秦时明月汉时关/万里长征人未还）、锦瑟（锦瑟无端五十弦/一弦一柱思华年）",
    "宋代词人字号：苏轼（字子瞻，号东坡居士）、辛弃疾（字幼安，号稼轩）、李清照（号易安居士）、柳永（字耆卿，人称奉旨填词柳三变）",
    "宋词名篇名句：念奴娇·赤壁怀古（大江东去/浪淘尽）、水调歌头（明月几时有/但愿人长久/千里共婵娟）、江城子·密州出猎（老夫聊发少年狂）、江城子·乙卯正月二十日夜记梦（十年生死两茫茫/不思量/自难忘）、青玉案·元夕（众里寻他千百度/蓦然回首/那人却在灯火阑珊处）、破阵子（醉里挑灯看剑/梦回吹角连营）",
    "婉约派名篇：声声慢（寻寻觅觅/冷冷清清/凄凄惨惨戚戚）、如梦令（知否知否/应是绿肥红瘦）、雨霖铃（寒蝉凄切/对长亭晚/执手相看泪眼）",
    "宋词其他名篇：满江红（怒发冲冠/三十功名尘与土/八千里路云和月）、钗头凤（红酥手/黄縢酒/满城春色宫墙柳）、示儿（死去元知万事空/王师北定中原日）、渔家傲·秋思（塞下秋来风景异/衡阳雁去无留意）",
    "词派：豪放派代表（苏轼、辛弃疾）；婉约派代表（柳永、李清照）",
    "建安风骨与魏晋：建安风骨代表三曹（曹操、曹丕、曹植）；观沧海（东临碣石/以观沧海/日月之行）、七步诗（煮豆燃豆萁/豆在釜中泣）；陶渊明田园诗（采菊东篱下/悠然见南山）",
    "诗派与群体：山水田园诗派（王维、孟浩然）、边塞诗派（高适、岑参、王昌龄）、燕歌行（战士军前半死生）、白雪歌（忽如一夜春风来/千树万树梨花开）、新乐府运动（白居易、元稹，主张文章合为时而著）、韩孟诗派（韩愈、孟郊，诗风险怪）、初唐四杰（王勃、杨炯、卢照邻、骆宾王）、大李杜（李白、杜甫）、小李杜（李商隐、杜牧）",
    "唐代名句：滕王阁序（落霞与孤鹜齐飞/秋水共长天一色）、登幽州台歌（前不见古人/后不见来者/念天地之悠悠）、泊秦淮（烟笼寒水月笼沙/夜泊秦淮近酒家）、赤壁（折戟沉沙铁未销/东风不与周郎便）、乌衣巷（旧时王谢堂前燕/飞入寻常百姓家）、回乡偶书（少小离家老大回/乡音无改鬓毛衰）、黄鹤楼（昔人已乘黄鹤去/此地空余黄鹤楼）",
    "格律术语：平仄（平声含阴平阳平，仄声含上声去声）、押韵（韵脚在偶数句末，近体诗一韵到底不换韵）、对仗（律诗颔联颈联必须对仗，工对为工整对仗）",
    "文学理论与先秦诗歌：诗经六义（风雅颂为体裁，赋比兴为表现手法）、楚辞（屈原作，代表作离骚，名句路漫漫其修远兮/吾将上下而求索）、关雎（关关雎鸠/在河之洲/窈窕淑女/君子好逑）、蒹葭（蒹葭苍苍/白露为霜/所谓伊人/在水一方）、乐府双璧（孔雀东南飞/木兰诗）、孔雀东南飞（五里一徘徊）",
    "文学批评与散文群体：文心雕龙（刘勰）、诗品（钟嵘，分上中下三品）、沧浪诗话（严羽，妙悟说，以禅喻诗）、人间词话（王国维，境界说，治学三境界含衣带渐宽终不悔/蓦然回首）、唐宋八大家（韩愈、柳宗元、欧阳修、苏洵、苏轼、苏辙、王安石、曾巩）、三苏（苏洵、苏轼、苏辙）、元曲四大家（关汉卿、白朴、马致远、郑光祖）、天净沙·秋思（枯藤老树昏鸦/小桥流水人家/断肠人在天涯）",
]

OPTIMIZER_SYSTEM = """你是古诗词知识图谱技能的"技能进化专家"（对应自进化 Agent 的
skill_manage 模块）。

## 当前模式：{mode}
{mode_desc}

## 核心原则（严格遵守）
1. **仅修复观察到的失败**：只针对输入样本里出现的问题类型做改动，不要扩展到
   "核对表里有但样本里没出现"的场景
2. **最小改动优先——patch 优先**：
   - 能在已有 Skill 里追加或改一条分支解决的，用 patch，**不要 rewrite 整份**
   - patch 的 old_text 只包含要改的那几行，从当前 Skill 中**逐字复制**（含标点空格），
     new_text 为替换后的内容（可在 old_text 前插入新知识点行）
3. **聚焦核心 + 类内完整**：按失败条数从高到低，**尽量覆盖所有失败类别**——梯度由新题维持，
   不需要刻意限制修复类别数；
   **但每一类须补充完整**——同一诗人的全部名篇名句、同一诗派的全部代表诗人、
   同一知识分支的全部术语（如修"苏轼"则补念奴娇+水调歌头+江城子密州出猎+江城子乙卯，
   修"边塞诗派"则补高适+岑参+王昌龄及其代表作）

## 评估环境说明
Agent 的回答按"关键词契约"评估：required 关键词（具体诗名/人名/字号/原句/术语）必须出现，
forbidden 不能出现，回答为完整文本（无需代码块）。修复应帮助 Agent 命中 required，
补全遗漏的具体知识点（原句/字号/术语等细节）。

## 信息完整性核对表（仅 rewrite 压缩时必须全部保留；patch 不受此约束）
{checklist}

## 当前 Skill 全文（token 数 {skill_tokens}）
{current_skill}

{history_section}

## 输出格式
{{
  "analysis": "本轮失败 N 条，主要失败类型是 XXX（或：全对，本轮为精炼优化）",
  "actions": [
    {{"action": "patch", "skill_name": "poetry_skill", "reason": "修复哪条失败/补充哪类知识点",
      "old_text": "从当前 Skill 逐字复制的最小片段", "new_text": "替换后的内容（可含新增知识点行）"}},
    {{"action": "rewrite", "reason": "仅在 Skill<60tok 空壳 或 refine 压缩 时使用", "content": "完整SKILL.md（含frontmatter）"}}
  ]
}}

只输出 JSON，不要有其他文字。若失败样本很少、没有清晰模式，可以返回 1 条甚至 0 条 action。
**fix 模式默认只用 patch；refine 压缩若无法下降≥10% 则返回 0 条 action（不要原样复制）。**"""


class SkillOptimizer:
    def __init__(self, skill_manager, model: str = "deepseek-chat"):
        self.skill_manager = skill_manager
        self.model = model
        self.last_analysis = ""
        self.client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com",
        )

    def optimize(self, failed_turns: list[dict], skill_manager=None) -> list[dict]:
        """分析失败样本，产出并执行 Skill 操作。返回已执行的动作列表。
        注意：failed_turns 为空时不能提前返回——零失败会进入 refine 精炼优化模式。"""
        sm = skill_manager or self.skill_manager

        current_skills = sm.load_all()
        current_skill = current_skills.get("poetry_skill", "")
        skill_tokens = len(ENC.encode(current_skill))

        # 模式判定
        if failed_turns:
            mode = "fix"
            mode_desc = (
                "本轮有失败样本。用 patch 修复所有失败类别，梯度由新题维持。\n"
                "  - patch 优先：在已有 Skill 上追加/修改局部知识点，**禁止 rewrite 整份**\n"
                "  - 只有当前 Skill 完全为空（<60 tokens）时才允许 rewrite\n"
                "  - **尽量覆盖所有失败类别**，不要只修 1~2 类\n"
                "  - **类内完整**：每类须补充完整——同诗人全部名篇、同诗派全部代表、同分支全部术语"
            )
            history_section = "## 失败样本（共 {} 条，都是 Agent 答错或遗漏知识点的）\n{}".format(
                len(failed_turns), self._format_failed_turns(failed_turns))
        else:
            mode = "refine"
            if skill_tokens > 1000:
                mode_desc = (
                    "本轮全对。Skill token 数 {} > 1000，进入**压缩优化**：rewrite 压缩冗余表述。\n"
                    "  - 压缩手段：合并同类知识点到同一行、省略重复的作者/朝代标注、精简说明文字\n"
                    "  - **每个知识实体（诗名/人名/字号/原句/术语）必须保留**（对照信息完整性核对表）\n"
                    "  - **压缩后 token 必须比当前下降 ≥ 10%**，否则不要返回 rewrite（返回 0 条 action）"
                ).format(skill_tokens)
            else:
                mode_desc = (
                    "本轮全对。Skill token 数 {} ≤ 1000，进入**扩展优化**：用 patch 补充 1~2 类\n"
                    "  遗漏知识点的细节（对照核对表检查过于简略处），每次只补 1~2 类留梯度"
                ).format(skill_tokens)
            history_section = "## 失败样本\n（本轮无失败样本，全部答对）"

        system_msg = OPTIMIZER_SYSTEM.format(
            mode=mode,
            mode_desc=mode_desc,
            checklist="\n".join(f"  - {c}" for c in INFO_CHECKLIST),
            skill_tokens=skill_tokens,
            current_skill=current_skill or "（暂无 Skill）",
            history_section=history_section,
        )

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system_msg}],
            temperature=0,
            max_tokens=3000,
        )
        actions = self._parse_actions(resp.choices[0].message.content.strip())
        return self._execute(actions, sm, mode=mode, skill_tokens=skill_tokens)

    # ── 内部 ──────────────────────────────────────────────────────────────────

    def _format_failed_turns(self, turns: list[dict]) -> str:
        lines = []
        for i, t in enumerate(turns, 1):
            lines.append(f"[{i}] 任务({t.get('title', '')}): {t['question']}")
            lines.append(f"    回答: {t['answer'][:200]}{'...' if len(t['answer']) > 200 else ''}")
            lines.append(f"    ✗ 判定: {t['fail_reason']}")
        return "\n".join(lines)

    def _parse_actions(self, raw: str) -> list[dict]:
        try:
            json_match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not json_match:
                print(f"  [Optimizer] 无法提取 JSON，原始输出: {raw[:200]}")
                return []
            data = json.loads(json_match.group())
            self.last_analysis = data.get("analysis", "")
            print(f"  [Optimizer] 分析: {self.last_analysis[:120]}")
            return data.get("actions", [])
        except json.JSONDecodeError as e:
            print(f"  [Optimizer] JSON 解析失败: {e}\n原始: {raw[:300]}")
            return []

    def _execute(self, actions: list[dict], sm, mode: str = "fix", skill_tokens: int = 0) -> list[dict]:
        executed = []
        for act in actions or []:
            try:
                action = act.get("action")
                reason = act.get("reason", "")
                if action == "rewrite":
                    content = act.get("content", "").strip()
                    new_tokens = len(ENC.encode(content))
                    # fix 模式：非空壳禁止 rewrite，强制 patch
                    if mode == "fix" and skill_tokens >= 60:
                        print(f"  [Optimizer] fix 模式禁止 rewrite（当前 Skill {skill_tokens}tok≥60 非空壳），跳过；请改用 patch")
                        continue
                    # refine 压缩有效性校验：必须下降 ≥10%
                    if mode == "refine" and skill_tokens > 1000 and new_tokens >= skill_tokens * 0.9:
                        print(f"  [Optimizer] refine 压缩无效（{new_tokens}tok 未显著低于 {skill_tokens}tok，下降<10%），跳过该 rewrite")
                        continue
                    if "SKILL.md" in content or len(content) < 80:
                        print(f"  [Optimizer] rewrite 内容异常，跳过: {content[:80]}")
                        continue
                    ok = sm.rewrite("poetry_skill", content, reason=reason)
                    if ok:
                        print(f"  [Optimizer] rewrite 成功: {skill_tokens}tok → {new_tokens}tok")
                elif action == "patch":
                    old_text = act.get("old_text", "")
                    new_text = act.get("new_text", "")
                    if not old_text or not new_text:
                        print(f"  [Optimizer] patch 缺少 old_text/new_text，跳过")
                        continue
                    ok = sm.patch(act.get("skill_name", "poetry_skill"),
                                  old_text, new_text, reason=reason)
                    if ok:
                        print(f"  [Optimizer] patch 成功: {reason[:60]}")
                elif action == "create":
                    ok = sm.create(act.get("skill_name", ""), act.get("content", ""), reason=reason)
                else:
                    ok = False
                if ok:
                    executed.append({"action": action, "reason": reason[:80]})
            except Exception as e:
                print(f"  [Optimizer] 执行动作失败: {e}")
        return executed
