"""
命令执行模块：安全策略、执行、线程安全输出

支持并行执行场景：多个命令同时运行时，用 threading.Lock 保护终端输出，
避免多命令的 [即将执行] / 结果信息交错混乱。subprocess.run 本身是线程安全的。

安全策略设计要点：
  - 对 python3 -c "..." 命令特殊处理：-c 参数内容是 Python 代码，
    引号内的 #（颜色值）、 /（URL/文件路径）是合法的，不应误杀
  - 用转义感知的引号剥离函数 _strip_quotes_aware，正确处理 \\" \\' 转义和三引号
  - 只检查引号外的 shell 元字符（|;&`）和重定向目标
"""

import re
import subprocess
import threading
import webbrowser
from pathlib import Path

# 模块级输出锁：并行执行时保护 print 调用
_output_lock = threading.Lock()


# ---------- 安全策略 ----------

def _strip_quotes_aware(text: str) -> str:
    """
    剥离引号内容（处理转义引号），返回只含引号外内容的文本。
    支持 \\" 和 \\' 转义，以及三引号 ''' 和 \"\"\"。
    用于安全检查：只检查引号外的 shell 元字符，避免误杀引号内的合法内容。
    """
    result = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in ('"', "'"):
            # 检测三引号
            triple = text[i:i + 3]
            if triple in ('"""', "'''"):
                quote = triple
                i += 3
                while i < len(text):
                    if text[i:i + 3] == quote:
                        i += 3
                        break
                    if text[i] == '\\' and i + 1 < len(text):
                        i += 2
                    else:
                        i += 1
                result.append('""')  # 占位
            else:
                quote = ch
                i += 1
                while i < len(text):
                    if text[i] == '\\' and i + 1 < len(text):
                        i += 2  # 跳过转义字符
                    elif text[i] == quote:
                        i += 1
                        break
                    else:
                        i += 1
                result.append('""')  # 占位
        else:
            result.append(ch)
            i += 1
    return ''.join(result)


def is_command_safe(command: str) -> bool:
    """
    检查命令是否安全可执行。白名单前缀 + 危险字符过滤 + 路径限制。

    对 python3 -c "..." 命令特殊处理：
    - -c 参数内容是 Python 代码，引号内的 #（注释/颜色值）、 /（URL/路径）是合法的
    - 只检查引号外的 shell 元字符和重定向目标
    """
    first_cmd = command.split('&&')[0].strip()
    first_word = first_cmd.split()[0] if first_cmd.split() else ''
    allowed_prefixes = (
        'python', 'python3', 'node', 'bash', 'sh', './', '.cursor/', 'skills/',
        'make', 'cmake', 'echo', 'open', 'mkdir', 'cat', 'bun', 'bunx',
        'cp', 'mv', 'ls',
    )
    if first_word not in allowed_prefixes and not any(first_cmd.startswith(p) for p in allowed_prefixes):
        print(f"  [DEBUG] is_command_safe 拒绝：首词 '{first_word}' 不在白名单")
        return False

    # 用转义感知的引号剥离，避免误杀引号内的 #、 / 等合法字符
    stripped = _strip_quotes_aware(command)

    # 检查引号外的危险 shell 元字符（# 不在此列表中，引号外的 # 在多数 shell 中是注释）
    if re.search(r'[|;&`]', stripped):
        print(f"  [DEBUG] is_command_safe 拒绝：引号外含危险字符 |;&`")
        return False
    if '$(' in stripped or '`' in stripped:
        print(f"  [DEBUG] is_command_safe 拒绝：含子shell")
        return False

    # 重定向检查：只检查引号外的 > 目标
    if '>' in stripped:
        parts = stripped.split('>')
        if len(parts) > 1:
            target = parts[1].strip().split()[0] if parts[1].strip() else ''
            if target and (target.startswith('/') or '..' in target):
                print(f"  [DEBUG] is_command_safe 拒绝：重定向目标不安全 '{target}'")
                return False

    # 绝对路径检查：只检查引号外的 / 开头或 ~
    # 注意：引号内的 http://、文件路径等是合法的，已在 _strip_quotes_aware 中剥离
    stripped_lstrip = stripped.lstrip()
    if stripped_lstrip.startswith('/'):
        print(f"  [DEBUG] is_command_safe 拒绝：以绝对路径开头")
        return False
    if '~' in stripped:
        print(f"  [DEBUG] is_command_safe 拒绝：含 ~ 家目录路径")
        return False

    return True


def execute_command(command: str, cwd: Path, auto_approve: bool = False, *, quiet: bool = False) -> str:
    """
    执行命令，返回执行结果字符串。
    参数：
      - command: 要执行的命令字符串
      - cwd: 工作目录
      - auto_approve: 是否自动批准（跳过用户确认）
      - quiet: 静默模式，不打印 [即将执行] 提示（供 live 任务面板使用）

    线程安全：所有 print 输出用 _output_lock 保护，支持并行执行场景。
    """
    with _output_lock:
        print(f"  [DEBUG] execute_command: cwd={cwd}")
        if not quiet:
            print(f"\n\033[2m[即将执行] {command}\033[0m")
        if not auto_approve:
            print("\033[33m是否执行此命令？(输入 y 确认，n 取消): \033[0m", end="", flush=True)

    # 用户确认在锁外进行，避免长时间持锁阻塞其他线程
    if not auto_approve:
        confirm = input().strip().lower()
        if confirm != 'y':
            return "⏹ 用户取消执行。"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=60
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            ret = f"✅ 执行成功\n{output}" if output else "✅ 执行成功（无输出）"
            with _output_lock:
                print(f"  [DEBUG] execute_command 成功: {ret[:100]}")
            return ret
        else:
            error = result.stderr.strip() or "未知错误"
            ret = f"❌ 执行失败 (返回码 {result.returncode})\n{error}"
            with _output_lock:
                print(f"  [DEBUG] execute_command 失败: {ret[:200]}")
            return ret
    except subprocess.TimeoutExpired:
        return "❌ 执行超时（超过 60 秒）"
    except Exception as e:
        return f"❌ 执行异常：{e}"


def handle_exec_tag(response_text: str, cwd: Path, auto_approve: bool = False) -> str:
    """
    解析响应中的 [EXEC: ...] 标记，执行命令，并将执行结果插入到响应中。
    返回修改后的完整文本。（兼容旧格式，单命令模式）
    """
    # 括号感知提取 [EXEC: ...]，容忍命令内含 [...]
    m = re.search(r'\[EXEC:\s*', response_text)
    if not m:
        return response_text
    i, depth = m.end(), 1
    while i < len(response_text) and depth > 0:
        ch = response_text[i]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                break
        elif ch in ('"', "'"):
            quote = ch
            i += 1
            while i < len(response_text) and response_text[i] != quote:
                if response_text[i] == '\\':
                    i += 1
                i += 1
        i += 1
    command = response_text[m.end():i].strip()
    command = re.sub(r'^`+|`+$', '', command).strip()  # 移除 markdown 反引号

    if not is_command_safe(command):
        safe_msg = "⚠️ 系统拒绝执行该命令（不符合安全策略）。"
        return response_text.replace(m.group(0), safe_msg)

    exec_result = execute_command(command, cwd, auto_approve)
    new_response = response_text.replace(m.group(0), exec_result)

    # 自动预览：如果执行成功且命令中包含 -o 输出文件，则尝试用浏览器打开
    if "✅ 执行成功" in exec_result and '-o' in command:
        output_match = re.search(r'-o\s+(\S+)', command)
        if output_match:
            out_path = Path(output_match.group(1))
            if out_path.exists():
                try:
                    webbrowser.open(str(out_path.absolute()))
                    new_response += f"\n已自动打开文件：{out_path.name}"
                except Exception as e:
                    new_response += f"\n⚠️ 无法打开文件：{e}"

    return new_response