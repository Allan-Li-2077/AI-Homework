"""skills 包 - FileSkill Harness 的技能包目录。

每个 skill 是一个独立的 .py 模块，需定义：
    SKILL_META : dict   模块元信息（名称/描述/参数/依赖），供 discovery 解析
    run(**kwargs)       执行入口，返回 dict 形式的结构化结果

模块内部的重型依赖（如 PIL、moviepy）应放在 run() 函数体内做局部 import，
这样 harness 在「发现 / 列表」阶段不会触发这些重依赖的导入，
从而实现渐进式加载。
"""
