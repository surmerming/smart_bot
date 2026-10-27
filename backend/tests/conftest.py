"""pytest 环境：强制 Mock LLM + 临时数据库，离线跑通全链路。"""
import os
import tempfile

# 必须在 import app 之前设置环境变量
os.environ["LLM_MODE"] = "mock"
os.environ["DEEPSEEK_API_KEY"] = ""
_tmp = tempfile.mkdtemp(prefix="xd_test_")
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["RATE_LIMIT_PER_MIN"] = "1000"  # 测试不触发限流

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# 模块级 TestClient 单例（模块内直接复用）
client = TestClient(app)
