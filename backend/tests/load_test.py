"""基础并发压测（plan V1.5 质量保障）：SSE 对话接口吞吐 / 成功率 / 延迟。

用法：
    # 进程内（Mock LLM，离线零成本，默认推荐）
    python backend/tests/load_test.py --concurrency 20 --total 120

    # 连真实运行中的后端（注意：真实模式会消耗 DeepSeek API 额度）
    python backend/tests/load_test.py --base http://127.0.0.1:8000 --concurrency 10 --total 50

输出：成功率 / 平均延迟 / p95 / p99 / 每秒请求数（RPS）。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# 进程内模式：强制 Mock LLM，离线、零成本、可重复；压测场景放开 IP 限流
os.environ.setdefault("LLM_MODE", "mock")
os.environ.setdefault("DEEPSEEK_API_KEY", "")
os.environ.setdefault("RATE_LIMIT_PER_MIN", "100000")

# 命中知识库 / 转人工 / 闲聊 三类消息，模拟真实流量分布
KB_MSGS = [
    "拆了包装还能退吗", "怎么申请7天无理由退货", "退款多久能到账", "怎么查我的物流信息",
    "能改收货地址吗", "运费谁出", "支持7天无理由退换吗", "忘记密码了怎么办",
]
HANDOVER_MSGS = ["我要投诉！你们产品太差了", "转人工", "我要打12315"]
CHAT_MSGS = ["今天天气怎么样", "你们老板是谁", "你好呀", "在吗"]


def pick_message() -> str:
    r = random.random()
    if r < 0.6:
        return random.choice(KB_MSGS)
    if r < 0.8:
        return random.choice(HANDOVER_MSGS)
    return random.choice(CHAT_MSGS)


async def worker(idx: int, total: int, base: str, results: list[float], errors: list[str]) -> None:
    from httpx import ASGITransport, AsyncClient

    if base:
        transport = None
        base_url = base
    else:
        from app.main import app  # noqa: F401

        transport = ASGITransport(app=app)
        base_url = "http://test"

    async with AsyncClient(transport=transport, base_url=base_url, timeout=30.0) as ac:
        for _ in range(total):
            try:
                r = await ac.post("/api/v1/chat/init", json={"session_id": None})
                data = r.json()
                sid, token = data["session_id"], data["visitor_token"]

                t0 = time.perf_counter()
                r2 = await ac.post("/api/v1/chat/stream", json={
                    "session_id": sid, "visitor_token": token, "message": pick_message(),
                })
                assert r2.status_code == 200
                assert "event: done" in r2.text
                results.append(time.perf_counter() - t0)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"worker{idx}: {exc}")


async def run(concurrency: int, total_each: int, base: str) -> int:
    results: list[float] = []
    errors: list[str] = []
    start = time.perf_counter()
    await asyncio.gather(*[worker(i, total_each, base, results, errors) for i in range(concurrency)])
    elapsed = time.perf_counter() - start

    n = len(results)
    ok = n - len(errors)
    print("=" * 60)
    print(f"小答 SSE 并发压测（{concurrency} 并发 × {total_each} 请求/worker）")
    print("=" * 60)
    print(f"  总请求：{n}  成功：{ok}  失败：{len(errors)}  成功率：{ok / n:.1%}" if n else "  无请求完成")
    if results:
        results.sort()
        p95 = results[int(n * 0.95) - 1]
        p99 = results[int(n * 0.99) - 1]
        print(f"  平均延迟：{statistics.mean(results) * 1000:.0f} ms")
        print(f"  P95：{p95 * 1000:.0f} ms  P99：{p99 * 1000:.0f} ms")
        print(f"  吞吐：{n / elapsed:.1f} req/s（总耗时 {elapsed:.1f}s）")
    for e in errors[:5]:
        print(f"  错误样例：{e[:120]}")
    return 0 if not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="SSE 对话接口并发压测")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--total", type=int, default=120, help="每个并发 worker 的请求数")
    parser.add_argument("--base", default="", help="真实后端地址；留空=进程内 Mock")
    args = parser.parse_args()
    return asyncio.run(run(args.concurrency, args.total, args.base.strip()))


if __name__ == "__main__":
    raise SystemExit(main())
