"""知识库加载与检索索引：TF-IDF 向量检索 + BM25 关键词检索 + RRF 融合。

MVP 阶段采用简化向量方案（本地 TF-IDF 特征，无外部 Embedding 依赖）；
接口以 KnowledgeBase 为界，生产期可无缝替换为「豆包 text-embedding + Qdrant」实现。
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

import jieba

# ---------- 分词 ----------
_STOPWORDS = {
    "的", "了", "吗", "呢", "啊", "吧", "哦", "呀", "是", "在", "我", "你", "他", "她",
    "它", "我们", "你们", "他们", "这个", "那个", "什么", "怎么", "会",
    "要", "想", "有", "没", "不", "吗", "请", "帮", "问", "下", "一下", "请问", "你们",
    "多久", "多少", "吗吗", "嗯", "好", "行", "对", "哈", "啊哈", "呀呀", "的的", "了了",
}


def tokenize(text: str) -> list[str]:
    """中文分词（jieba）+ 停用词过滤 + 小写归一。"""
    words = jieba.lcut(text.lower())
    return [w.strip() for w in words if w.strip() and w not in _STOPWORDS and not w.isspace()]


_CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")


def tokenize_full(text: str, bigram_weight: float = 0.7) -> list[tuple[str, float]]:
    """混合特征：jieba 词 + 中文连续字符 bigram（提升口语化/拆字变体匹配鲁棒性）。

    例：「拆了包装还能退吗」→ 词[拆,包装,还,能,退] + bigram[拆了,了包,包装,装还,还能,能退,退吗]
    「拆封了还能退吗」→ bigram[拆封,封了,了还,还能,能退,退吗]，共享 还能/能退/退吗。
    """
    feats: list[tuple[str, float]] = [(w, 1.0) for w in tokenize(text)]
    chars = "".join(_CHINESE_RE.findall(text))
    for i in range(len(chars) - 1):
        feats.append(("bg_" + chars[i:i + 2], bigram_weight))
    return feats


CATEGORY_ZH = {
    "aftersales": "售后",
    "presales": "售前",
    "transaction": "交易",
    "account": "账号",
}

@dataclass
class FAQItem:
    id: str
    category: str
    standard_question: str
    variants: list[str]
    answer: str
    risk_level: str  # low / mid / high
    follow_up: list[str] = field(default_factory=list)

    @property
    def category_zh(self) -> str:
        return CATEGORY_ZH.get(self.category, self.category)

    @property
    def search_text(self) -> str:
        """检索文本 = 标准问法 + 变体问法 + 答案（小 chunk 保精准，父文档保完整）。"""
        return " ".join([self.standard_question, *self.variants, self.answer])

    def tokenized(self) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
        """混合特征：(问法特征, 答案特征)。答案降权，避免稀释问法匹配。"""
        q = tokenize_full(" ".join([self.standard_question, *self.variants]), bigram_weight=0.7)
        a = tokenize_full(self.answer, bigram_weight=0.2)
        return q, a

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "standard_question": self.standard_question,
            "variants": self.variants,
            "answer": self.answer,
            "risk_level": self.risk_level,
            "follow_up": self.follow_up,
        }


# ---------- TF-IDF 向量索引（简化向量）----------
class TfidfIndex:
    def __init__(self) -> None:
        self.doc_token_lists: list[list[str]] = []   # 每篇文档分词
        self.vocab: dict[str, int] = {}              # 词 -> 列索引
        self.idf: list[float] = []
        self.doc_vectors: list[dict[int, float]] = []  # 每篇 {词idx: 归一化权重}
        self._avgdl: float = 0.0
        self._df: Counter = Counter()                # 词 -> 文档频率（BM25 用）

    def build(self, doc_token_lists: list[list[str]], doc_weights: list[list[float]] | None = None) -> None:
        """构建索引。doc_weights 与 token 一一对应，用于对答案等次要部分降权。"""
        self.doc_token_lists = doc_token_lists
        n = len(doc_token_lists)
        # 1. 统计 df、构建词表
        for tokens in doc_token_lists:
            for w in set(tokens):
                self._df[w] += 1
                if w not in self.vocab:
                    self.vocab[w] = len(self.vocab)
        # 2. IDF
        self.idf = [0.0] * len(self.vocab)
        for w, idx in self.vocab.items():
            self.idf[idx] = math.log((n + 1.0) / (self._df[w] + 1.0)) + 1.0
        # 3. 每篇 TF-IDF（加权）+ L2 归一化
        self.doc_vectors = []
        for i, tokens in enumerate(doc_token_lists):
            weights = doc_weights[i] if doc_weights else [1.0] * len(tokens)
            tf: Counter = Counter()
            for w, wgt in zip(tokens, weights):
                tf[w] += wgt
            vec: dict[int, float] = {}
            norm2 = 0.0
            for w, cnt in tf.items():
                idx = self.vocab.get(w)
                if idx is None:
                    continue
                wgt = (1.0 + math.log(cnt)) * self.idf[idx]
                vec[idx] = wgt
                norm2 += wgt * wgt
            if norm2 > 0:
                inv = 1.0 / math.sqrt(norm2)
                vec = {k: v * inv for k, v in vec.items()}
            self.doc_vectors.append(vec)
        # 4. 平均文档长度（BM25）
        self._avgdl = sum(len(t) for t in doc_token_lists) / max(n, 1)

    def dense_scores(self, query_tokens: list[str]) -> list[float]:
        """查询向量与每篇文档的余弦相似度（0~1）。"""
        q_vec: dict[int, float] = {}
        tf = Counter(query_tokens)
        norm2 = 0.0
        for w, cnt in tf.items():
            idx = self.vocab.get(w)
            if idx is None:
                continue
            wgt = (1.0 + math.log(cnt)) * self.idf[idx]
            q_vec[idx] = wgt
            norm2 += wgt * wgt
        if norm2 > 0:
            inv = 1.0 / math.sqrt(norm2)
            q_vec = {k: v * inv for k, v in q_vec.items()}
        scores = []
        for doc_vec in self.doc_vectors:
            s = 0.0
            for idx, wgt in q_vec.items():
                if idx in doc_vec:
                    s += wgt * doc_vec[idx]
            scores.append(s)
        return scores

    # ---- BM25 ----
    def bm25_scores(self, query_tokens: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
        n = len(self.doc_token_lists)
        scores = []
        for tokens in self.doc_token_lists:
            dl = len(tokens)
            s = 0.0
            for w in set(query_tokens):
                tf = tokens.count(w)
                if tf == 0:
                    continue
                df = self._df.get(w, 0)
                idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)
                s += idf * (tf * (k1 + 1.0)) / (tf + k1 * (1.0 - b + b * dl / max(self._avgdl, 1e-9)))
            scores.append(s)
        return scores


# ---------- 否定词 / 风险词检测 ----------
_NEGATION_PATTERNS = [
    r"不[支持能]",
    r"不能",
    r"没(有|法|办)",
    r"难道",
    r"对吧",
    r"不是吗",
    r"真的假的",
    r"确定.*吗",
    r"是假",
    r"不支持",
    r"别想",
    r"别指望",
]
_RISK_KEYWORDS = [
    "投诉", "举报", "曝光", "12315", "315", "消协", "市场监管局", "工商局",
    "起诉", "律师", "法律", "法院", "报警", "警察", "诈骗", "骗子",
    "赔偿", "赔钱", "精神损失", "假一赔", "退款金额", "改价", "补差价",
    "注销", "盗号", "账号被盗", "异地登录", "陌生订单", "封号",
]

_HANDOVER_KEYWORDS = ["转人工", "找客服", "找真人", "人工客服", "人工", "真人", "活人", "客服电话", "转接"]

# 快速回复 = 用户确认某 FAQ 时（确认中状态）
_CONFIRM_WORDS = {"是", "对", "嗯", "好", "行", "是的", "对的", "没错", "ok", "可以", "要的", "要"}
_DENY_WORDS = {"不是", "不对", "没有", "不是的", "no", "算了", "不用", "不了"}


def has_negation(text: str) -> bool:
    return any(re.search(p, text) for p in _NEGATION_PATTERNS)


def has_risk_keyword(text: str) -> bool:
    return any(k in text for k in _RISK_KEYWORDS)


def wants_human(text: str) -> bool:
    return any(k in text for k in _HANDOVER_KEYWORDS)


def is_confirmation(text: str) -> bool:
    t = text.strip().lower()
    return t in _CONFIRM_WORDS


def is_denial(text: str) -> bool:
    t = text.strip().lower()
    return any(t == w or t.startswith(w) for w in _DENY_WORDS)


# ---------- 知识库主体 ----------
class KnowledgeBase:
    def __init__(self) -> None:
        self.faqs: list[FAQItem] = []
        self._index: Optional[TfidfIndex] = None
        self._categories: Counter = Counter()
        # V1.5 缓存联动：知识库重建时版本 +1，高频缓存据此整体失效
        self.version: int = 0

    # ---- 构建 ----
    def load(self, json_path: str) -> None:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        self.faqs = [FAQItem(**item) for item in data["faqs"]]
        self._categories = Counter(faq.category for faq in self.faqs)
        # 问法权重 1.0，答案权重 0.35（防答案稀释问法匹配）
        token_lists: list[list[str]] = []
        weight_lists: list[list[float]] = []
        for faq in self.faqs:
            q, a = faq.tokenized()
            token_lists.append([t for t, _ in q + a])
            weight_lists.append([w for _, w in q + a])
        self._index = TfidfIndex()
        self._index.build(token_lists, weight_lists)
        self.version += 1

    def category_stats(self) -> dict:
        return dict(self._categories)

    # ---- 检索 ----
    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """混合检索：Dense(向量) + Sparse(BM25) 双路召回 → RRF 融合重排。

        返回按融合分排序的候选，每个候选携带 dense_score（0~1，用于置信度阈值判断）。
        """
        if not self.faqs or self._index is None:
            return []
        qt = tokenize(query)
        if not qt:
            return []
        n = len(self.faqs)

        dense = self._index.dense_scores(qt)
        bm25 = self._index.bm25_scores(qt)
        k = 60

        dense_rank = sorted(range(n), key=lambda i: (-dense[i], i))
        bm25_rank = sorted(range(n), key=lambda i: (-bm25[i], i))

        fused: dict[int, float] = defaultdict(float)
        for rank, i in enumerate(dense_rank):
            fused[i] += 1.0 / (k + rank + 1)
        for rank, i in enumerate(bm25_rank):
            fused[i] += 1.0 / (k + rank + 1)

        top_idx = sorted(fused, key=lambda i: (-fused[i], -dense[i]))[:top_k]
        results = []
        for i in top_idx:
            results.append({
                "faq": self.faqs[i],
                "dense_score": float(dense[i]),
                "bm25_score": float(bm25[i]),
                "combined": float(fused[i]),
            })
        return results

    def find_duplicates(self, threshold: float = 0.95) -> list[tuple[str, str, float]]:
        """重复 FAQ 检测：检索自身标准问法，相似度超阈值提示撞车。"""
        out = []
        for faq in self.faqs:
            hits = [h for h in self.search(faq.standard_question, top_k=4) if h["faq"].id != faq.id]
            for h in hits:
                if h["dense_score"] >= threshold:
                    out.append((faq.id, h["faq"].id, round(h["dense_score"], 3)))
        return out

    def get_faq(self, faq_id: str) -> Optional[FAQItem]:
        for faq in self.faqs:
            if faq.id == faq_id:
                return faq
        return None


# 全局单例：main.py 启动时调用 kb.load(...) 初始化
kb = KnowledgeBase()
