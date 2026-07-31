import ast
import json
import operator
import re
import sys

OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def evaluate(node):
    if isinstance(node, ast.Expression):
        return evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return OPS[type(node.op)](evaluate(node.left), evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](evaluate(node.operand))
    raise ValueError("表达式包含不支持的内容")


payload = json.load(sys.stdin)
match = re.search(r"[-+*/().\d\s]+", payload["request"])
if not match or not match.group().strip():
    raise ValueError("没有找到算术表达式")
expression = match.group().strip()
value = evaluate(ast.parse(expression, mode="eval"))
json.dump({"result": {"expression": expression, "value": value}}, sys.stdout)
