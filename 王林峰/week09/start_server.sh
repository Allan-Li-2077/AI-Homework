#!/bin/bash
# vLLM OpenAI兼容服务启动脚本 作业专用
# 模型路径同bench_throughput.py
MODEL_PATH="/mnt/d/badou/项目材料准备/pretrain_models/Qwen2-0.5B-Instruct"
HOST="0.0.0.0"
PORT=8000
GPU_MEM_UTIL=0.6
MAX_MODEL_LEN=2048
DTYPE="float16"

# 先杀死残留vllm进程
echo "清理残留vLLM服务进程..."
pkill -f vllm.entrypoints.openai.api_server
sleep 2

# 启动vLLM api server
echo "启动vLLM OpenAI服务，地址：http://$HOST:$PORT/v1"
echo "模型路径: $MODEL_PATH"
python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL_PATH" \
  --host $HOST \
  --port $PORT \
  --gpu-memory-utilization $GPU_MEM_UTIL \
  --max-model-len $MAX_MODEL_LEN \
  --dtype $DTYPE \
  --enforce-eager