"""信息检索 SubAgent。

内置一个技术知识库（list of dict），根据查询关键词对每条知识的 tags / keywords /
title / content 进行加权匹配评分并排序返回。空查询时返回前若干条作为热门条目。
仅使用标准库，无任何外部依赖。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

import asyncio
from ..base import BaseSubAgent
from ...core.models import SubTask


# 内置技术知识库：每条含 title / keywords / content / tags 字段
KNOWLEDGE_BASE: List[Dict[str, Any]] = [
    {
        "title": "Python GIL 与并发模型",
        "keywords": ["python", "gil", "并发", "线程", "多线程"],
        "tags": ["python", "concurrency"],
        "content": "Python 的全局解释器锁（GIL）限制同一时刻只有一个线程执行字节码，"
                   "CPU 密集型任务应使用 multiprocessing 或 C 扩展绕开 GIL，"
                   "IO 密集型任务可使用多线程或 asyncio 获得良好并发性能。",
    },
    {
        "title": "asyncio 异步编程基础",
        "keywords": ["asyncio", "异步", "协程", "event loop", "async", "await", "异步编程"],
        "tags": ["python", "async", "concurrency"],
        "content": "asyncio 是 Python 的异步 IO 框架，通过事件循环调度协程。"
                   "使用 async def 定义协程，await 等待可等待对象。"
                   "适合高并发网络请求、数据库连接等 IO 密集场景。",
    },
    {
        "title": "Docker 容器化最佳实践",
        "keywords": ["docker", "容器", "镜像", "dockerfile", "构建"],
        "tags": ["docker", "devops"],
        "content": "Docker 通过 Dockerfile 描述镜像构建过程。最佳实践包括："
                   "使用多阶段构建减小镜像体积、利用层缓存、使用 .dockerignore、"
                   "以非 root 用户运行容器、固定基础镜像版本标签。",
    },
    {
        "title": "Kubernetes 核心概念",
        "keywords": ["kubernetes", "k8s", "pod", "deployment", "service", "编排"],
        "tags": ["kubernetes", "devops"],
        "content": "Kubernetes 是容器编排系统，核心对象包括 Pod（最小调度单元）、"
                   "Deployment（无状态应用部署）、Service（服务发现与负载均衡）、"
                   "ConfigMap/Secret（配置管理）。通过声明式 API 管理集群状态。",
    },
    {
        "title": "Redis 数据结构与缓存策略",
        "keywords": ["redis", "缓存", "内存数据库", "数据结构", "过期"],
        "tags": ["redis", "cache", "database"],
        "content": "Redis 支持 string/list/hash/set/zset/stream 等数据结构。"
                   "常用缓存策略：Cache-Aside（旁路缓存）、Read/Write-Through、Write-Behind。"
                   "需合理设置过期时间与内存淘汰策略（如 allkeys-lru）防止内存溢出。",
    },
    {
        "title": "消息队列选型与对比",
        "keywords": ["消息队列", "kafka", "rabbitmq", "mq", "异步通信"],
        "tags": ["mq", "messaging"],
        "content": "常见消息队列：Kafka（高吞吐、日志/流处理）、RabbitMQ（灵活路由、"
                   "AMQP 协议）、RocketMQ（事务消息）、Pulsar（计算存储分离）。"
                   "选型需考虑吞吐、延迟、顺序性、可靠性、协议支持。",
    },
    {
        "title": "微服务架构设计原则",
        "keywords": ["微服务", "架构", "服务拆分", "领域驱动", "ddd"],
        "tags": ["microservice", "architecture"],
        "content": "微服务按业务能力拆分，每个服务独立部署、独立数据库。"
                   "需关注：服务边界（DDD 限界上下文）、数据一致性（Saga/最终一致）、"
                   "服务间通信（REST/gRPC）、链路追踪、容错（熔断/限流/降级）。",
    },
    {
        "title": "可观测性与监控体系",
        "keywords": ["监控", "可观测性", "metrics", "prometheus", "grafana", "trace"],
        "tags": ["monitoring", "observability"],
        "content": "可观测性三大支柱：Metrics（指标，Prometheus + Grafana）、"
                   "Logging（日志，ELK/EFK）、Tracing（链路追踪，Jaeger/Zipkin）。"
                   "通过 RED（Rate/Errors/Duration）与 USE 方法论建立核心指标。",
    },
    {
        "title": "CI/CD 流水线设计",
        "keywords": ["ci", "cd", "持续集成", "持续部署", "流水线", "jenkins", "gitlab"],
        "tags": ["cicd", "devops"],
        "content": "CI/CD 流水线包含：代码检出、依赖安装、Lint、单元测试、构建镜像、"
                   "安全扫描、部署到预发、集成测试、灰度发布、生产发布。"
                   "强调快速反馈、自动化、可回滚。",
    },
    {
        "title": "数据库索引优化",
        "keywords": ["数据库", "索引", "b树", "查询优化", "慢查询"],
        "tags": ["database", "optimization"],
        "content": "数据库索引使用 B+Tree 结构加速查询。优化要点："
                   "在 WHERE/JOIN/ORDER BY 字段建索引、使用覆盖索引避免回表、"
                   "避免索引失效（函数操作、类型转换、前导通配符）、"
                   "通过 EXPLAIN 分析执行计划、定期重建碎片化索引。",
    },
    {
        "title": "多级缓存架构",
        "keywords": ["缓存", "多级缓存", "本地缓存", "分布式缓存", "一致性"],
        "tags": ["cache", "architecture"],
        "content": "多级缓存：本地缓存（进程内，如 LRU dict）→ 分布式缓存（Redis）→ 数据库。"
                   "需处理缓存穿透（布隆过滤器）、缓存击穿（互斥锁/热点永不过期）、"
                   "缓存雪崩（过期时间加随机抖动）、缓存与 DB 一致性（延迟双删/订阅 binlog）。",
    },
    {
        "title": "负载均衡算法",
        "keywords": ["负载均衡", "nginx", "轮询", "一致性哈希", "lvs"],
        "tags": ["loadbalancer", "network"],
        "content": "常见负载均衡算法：轮询（Round Robin）、加权轮询、最少连接、"
                   "源地址哈希、一致性哈希（适合缓存节点）。"
                   "四层负载（LVS）基于 IP/端口转发，七层负载（Nginx）基于 HTTP 头路由。",
    },
    {
        "title": "分布式日志收集",
        "keywords": ["日志", "logging", "elk", "log", "收集"],
        "tags": ["logging", "observability"],
        "content": "分布式系统日志收集：应用输出结构化 JSON 日志（含 trace_id），"
                   "通过 Filebeat/Fluentd 采集，Kafka 缓冲，Logstash 处理，"
                   "Elasticsearch 存储，Kibana 查询可视化。注意日志级别与采样。",
    },
    {
        "title": "应用安全防护",
        "keywords": ["安全", "sql注入", "xss", "csrf", "鉴权", "oauth"],
        "tags": ["security"],
        "content": "Web 安全防护：防 SQL 注入（参数化查询）、防 XSS（输出转义/CSP）、"
                   "防 CSRF（Token/SameSite Cookie）、防重放（Nonce/时间戳）。"
                   "认证授权使用 OAuth2/OIDC、JWT，敏感数据加密存储与传输（TLS）。",
    },
    {
        "title": "RESTful API 设计规范",
        "keywords": ["api", "rest", "restful", "接口", "http", "api设计"],
        "tags": ["api", "design"],
        "content": "RESTful API 设计：使用 HTTP 动词语义（GET/POST/PUT/DELETE）、"
                   "资源用名词复数、版本化（/v1/）、统一错误格式、"
                   "分页/过滤/排序参数规范化、幂等性设计、HATEOAS。"
                   "文档用 OpenAPI/Swagger。",
    },
    {
        "title": "Python 装饰器与元编程",
        "keywords": ["python", "装饰器", "decorator", "元类", "metaclass"],
        "tags": ["python", "advanced"],
        "content": "装饰器是接收函数返回函数的可调用对象，用于横切关注点（日志/缓存/鉴权）。"
                   "使用 functools.wraps 保留元信息。类装饰器与元类（metaclass）"
                   "可在类创建时修改行为，实现 ORM、插件注册等高级模式。",
    },
]


def _tokenize(text: str) -> List[str]:
    """将查询切分为小写关键词 token（英文按词、中文按连续汉字段切分）。"""
    if not text:
        return []
    raw = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fa5]+", text.lower())
    return [t for t in raw if t]


def _score_entry(entry: Dict[str, Any], tokens: List[str]) -> float:
    """根据 token 对单条知识计算加权匹配分数。

    权重：tags(3.0) > keywords(2.0) > title(1.5) > content(0.5)。
    """
    if not tokens:
        return 0.0
    keywords = [str(k).lower() for k in entry.get("keywords", [])]
    tags = [str(t).lower() for t in entry.get("tags", [])]
    title = str(entry.get("title", "")).lower()
    content = str(entry.get("content", "")).lower()
    score = 0.0
    for tok in tokens:
        # tags 权重最高，其次 keywords，再 title，最后 content
        if any(tok == t or tok in t or t in tok for t in tags):
            score += 3.0
        if any(tok == k or tok in k or k in tok for k in keywords):
            score += 2.0
        if tok in title:
            score += 1.5
        if tok in content:
            score += 0.5
    return score


class InfoRetrievalAgent(BaseSubAgent):
    """信息检索 Agent：基于内置知识库做关键词匹配检索。"""

    def __init__(self, max_concurrency: int = 5) -> None:
        super().__init__(
            name="info_retrieval_agent",
            capabilities="info_retrieval",
            max_concurrency=max_concurrency,
        )

    async def process(self, subtask: SubTask) -> Dict[str, Any]:
        # 模拟 IO 让出事件循环，使并行调度可观测（内置 Agent 为纯内存计算）
        await asyncio.sleep(0.1)
        # 容错：input_data 可能为 None 或非 dict
        data = subtask.input_data or {}
        if not isinstance(data, dict):
            data = {"query": str(data)}
        query = str(data.get("query", "") or "").strip()

        if not query:
            # 空查询：返回前若干条作为热门条目
            popular = KNOWLEDGE_BASE[:5]
            matches = [
                {
                    "title": e.get("title", ""),
                    "content": e.get("content", ""),
                    "score": 0.0,
                    "tags": e.get("tags", []),
                }
                for e in popular
            ]
            return {"query": "", "matches": matches, "count": len(matches)}

        tokens = _tokenize(query)
        scored = [(entry, _score_entry(entry, tokens)) for entry in KNOWLEDGE_BASE]
        # 过滤掉零分项并按分数倒序
        scored = [(e, s) for e, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)

        matches = [
            {
                "title": e.get("title", ""),
                "content": e.get("content", ""),
                "score": round(s, 2),
                "tags": e.get("tags", []),
            }
            for e, s in scored[:10]
        ]
        return {"query": query, "matches": matches, "count": len(matches)}
