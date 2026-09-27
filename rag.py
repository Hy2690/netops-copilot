"""rag.py — RAG 知识库：把运维文档变成 Agent 可检索的"长期记忆"。

用法：
    python rag.py rebuild                 # 重建向量索引（修改 knowledge/ 后执行）
    python rag.py query "BGP 中断怎么处理"  # 命令行测试检索效果
    python rag.py stats                   # 查看知识库规模

原理：knowledge/*.md → 切分成 chunk → bge-m3 嵌入为向量 → 存入 ChromaDB；
      Agent 通过 tools.py 的 search_knowledge_base 工具按语义检索最相关的片段。
"""

import os
import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

BASE_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = BASE_DIR / "knowledge"
CHROMA_DIR = str(BASE_DIR / "chroma_db")
COLLECTION = "netops_kb"
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "bge-m3")

# 针对中文运维文档的切分策略：优先按 Markdown 标题/段落边界切，保持语义完整
_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=400,
    chunk_overlap=60,
    separators=["\n## ", "\n### ", "\n\n", "\n", "。", "；"],
)

_vs_cache = None  # 进程内缓存，避免每次检索都重新加载索引


def _embeddings():
    return OllamaEmbeddings(model=EMBED_MODEL)


def load_documents():
    """读取 knowledge/ 下所有 Markdown 文档，切分为 chunk 并标注来源文件。"""
    docs = []
    for path in sorted(KNOWLEDGE_DIR.glob("**/*.md")):
        text = path.read_text(encoding="utf-8")
        docs.append(Document(page_content=text, metadata={"source": path.name}))
    if not docs:
        raise FileNotFoundError(f"{KNOWLEDGE_DIR} 下没有找到任何 .md 文档")
    return _SPLITTER.split_documents(docs)


def build_index():
    """全量重建向量索引（knowledge/ 有改动后执行）。"""
    from langchain_chroma import Chroma

    chunks = load_documents()
    vs = Chroma.from_documents(
        documents=chunks,
        embedding=_embeddings(),
        persist_directory=CHROMA_DIR,
        collection_name=COLLECTION,
    )
    print(f"索引构建完成：{len(chunks)} 个 chunk → {CHROMA_DIR}（嵌入模型: {EMBED_MODEL}）")
    return vs


def _get_store():
    """加载已有索引（首次调用时加载，之后走缓存）。"""
    global _vs_cache
    if _vs_cache is None:
        from langchain_chroma import Chroma

        if not Path(CHROMA_DIR).exists():
            raise FileNotFoundError("向量索引不存在，请先运行: python rag.py rebuild")
        _vs_cache = Chroma(
            persist_directory=CHROMA_DIR,
            embedding_function=_embeddings(),
            collection_name=COLLECTION,
        )
    return _vs_cache


def search(query: str, k: int = 3) -> str:
    """语义检索最相关的 k 个知识片段，返回带来源标注的文本（供 Agent 工具调用）。"""
    results = _get_store().similarity_search_with_score(query, k=k)
    if not results:
        return "知识库中没有检索到相关内容。"
    blocks = []
    for doc, distance in results:
        relevance = max(0.0, 1 - distance)  # Chroma 返回的是距离，近似换算为相关度
        blocks.append(
            f"【来源: {doc.metadata.get('source', '未知')} | 相关度: {relevance:.2f}】\n"
            f"{doc.page_content.strip()}"
        )
    return "\n\n---\n\n".join(blocks)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == "rebuild":
        build_index()
    elif cmd == "query" and len(sys.argv) >= 3:
        print(search(" ".join(sys.argv[2:])))
    elif cmd == "stats":
        chunks = load_documents()
        n_files = len(list(KNOWLEDGE_DIR.glob("**/*.md")))
        print(f"知识库共 {n_files} 份文档，切分为 {len(chunks)} 个 chunk")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
