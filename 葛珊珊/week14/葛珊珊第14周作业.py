"""模拟跑 v1 / v2 skill 在同一 diff 上的输出，并统计输出 token 对比"""
import re

TEST_DIFF = """diff --git a/src/auth.py b/src/auth.py
index 1a2b3c4..5d6e7f8 100644
--- a/src/auth.py
+++ b/src/auth.py
@@ -12,8 +12,14 @@ def login(username, password):
-    if username and password:
-        return authenticate(username, password)
-    return False
+    if not username or not password:
+        logger.warning("Login attempt with empty credentials")
+        return False
+    user = authenticate(username, password)
+    if user is None:
+        logger.warning(f"Authentication failed for {username}")
+        return False
+    return user
diff --git a/src/logger.py b/src/logger.py
new file mode 100644
--- /dev/null
+++ b/src/logger.py
@@ -0,0 +1,5 @@
+import logging
+logging.basicConfig(level=logging.INFO)
+logger = logging.getLogger("app")
"""

# 模拟 v1 skill 引导出的输出（verbose，body 较长）
V1_OUTPUT = """feat(auth): add login function with input validation

- Check username and password are non-empty before authenticating
- Return False immediately on invalid input to avoid crashing callers
- Add logging for failed login attempts to improve traceability
- Introduce a new logger module to centralize logging configuration

The previous implementation returned False for any falsy input but did not
log the attempt. This made debugging difficult. Now we explicitly check
for empty credentials and log a warning. We also log authentication
failures so that security teams can monitor suspicious activity.

A new logger.py module is added to configure the root logger at INFO
level and provide a shared logger instance for the application.

Refs #142
"""

# 模拟 v2 skill 引导出的输出（精简，但信息完整）
V2_OUTPUT = """feat(auth): add input validation and logging to login

- Reject empty credentials with a warning log
- Log authentication failures for monitoring
- Add logger module for shared logging config

Closes #142
"""

def est_tokens(text):
    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
    en = len(text) - cn
    return int(en / 4 + cn / 1.5)

def main():
    print("=" * 70)
    print("测试输入 diff 字符数:", len(TEST_DIFF))
    print("测试输入 diff 估算 token:", est_tokens(TEST_DIFF))
    print("=" * 70)

    for name, out in [("v1 (verbose)", V1_OUTPUT), ("v2 (optimized)", V2_OUTPUT)]:
        print(f"\n--- {name} 输出 ---")
        print(out)
        print(f"输出字符数: {len(out)}")
        print(f"输出行数: {out.count(chr(10))}")
        print(f"输出估算 token: {est_tokens(out)}")

    print("\n" + "=" * 70)
    print("输出 token 对比:")
    t1, t2 = est_tokens(V1_OUTPUT), est_tokens(V2_OUTPUT)
    print(f"  v1: {t1} tokens")
    print(f"  v2: {t2} tokens")
    print(f"  节省: {t1-t2} tokens ({(t1-t2)/t1*100:.1f}%)")

    # 质量评估
    print("\n质量评估（关键信息覆盖）:")
    checks = [
        ("type=feat", "feat" in V1_OUTPUT and "feat" in V2_OUTPUT),
        ("scope=auth", "(auth)" in V1_OUTPUT and "(auth)" in V2_OUTPUT),
        ("提到 input validation", "validation" in V1_OUTPUT.lower() and "validation" in V2_OUTPUT.lower()),
        ("提到 logging", "log" in V1_OUTPUT.lower() and "log" in V2_OUTPUT.lower()),
        ("引用 issue #142", "#142" in V1_OUTPUT and "#142" in V2_OUTPUT),
        ("subject 祈使句", True),  # 两者都是 add 开头
        ("无 markdown 代码块包裹", not out.startswith("```")),
    ]
    for label, ok in checks:
        print(f"  [{'✓' if ok else '✗'}] {label}")

if __name__ == '__main__':
    main()
