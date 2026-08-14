import ast, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
base = os.path.join(os.path.dirname(__file__), 'src')
files = ['llm_client.py','customer_tools.py','react_loop.py','agents.py','serve.py','eval_compare.py']
for f in files:
    p = os.path.join(base, f)
    ast.parse(open(p, encoding='utf-8').read())
print('[OK] All Python files syntax valid')

# 测试客服工具 mock 数据
from customer_tools import query_order, query_logistics, apply_refund, query_faq, escalate_human
print('\n--- query_order A100002 ---')
print(query_order('A100002'))
print('\n--- query_logistics YT7654321 ---')
print(query_logistics('YT7654321'))
print('\n--- apply_refund A100003 ---')
print(apply_refund('A100003', '质量问题'))
print('\n--- query_faq 退货政策 ---')
print(query_faq('退货政策'))
print('\n--- escalate_human ---')
print(escalate_human('客户投诉退款未到账'))
