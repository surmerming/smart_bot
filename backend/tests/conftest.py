"""pytest 环境：强制 Mock LLM + 临时数据库 + 临时知识库副本，离线跑通全链路。"""
import os
import shutil
import tempfile

# 必须在 import app 之前设置环境变量
os.environ["LLM_MODE"] = "mock"
os.environ["DEEPSEEK_API_KEY"] = ""
_tmp = tempfile.mkdtemp(prefix="xd_test_")
os.environ["DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["RATE_LIMIT_PER_MIN"] = "1000"  # 测试不触发限流
# 知识库也隔离到临时副本：V2.0 知识库后台测试会写 faq.json，禁止污染真实 Source of Truth
_kb_src = os.path.join(os.path.dirname(__file__), "../../knowledge_base/faq.json")
os.makedirs(os.path.join(_tmp, "kb"), exist_ok=True)
_kb_copy = os.path.join(_tmp, "kb", "faq.json")
shutil.copy(_kb_src, _kb_copy)
os.environ["KB_PATH"] = _kb_copy

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

# 模块级 TestClient 单例（模块内直接复用）
client = TestClient(app)
