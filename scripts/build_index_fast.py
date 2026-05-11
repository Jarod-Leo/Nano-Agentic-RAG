#!/usr/bin/env python3
"""快速构建 FAISS + BM25 索引（支持 GPU 加速 + 多进程）

用法:
  # 单卡 GPU + 大 batch
  python scripts/build_index_fast.py \
    --corpus data/manuals/corpus.json \
    --index-dir data/manuals/indexes/ \
    --device cuda:0 \
    --batch-size 256

  # 多卡并行（数据分片）
  python scripts/build_index_fast.py \
    --corpus data/manuals/corpus.json \
    --index-dir data/manuals/indexes/ \
    --devices cuda:0 cuda:1 cuda:2 cuda:3 \
    --batch-size 256 \
    --workers 4
"""
import argparse
import json
import os
import pickle
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from threading import Lock
import multiprocessing as mp

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BGE_M3_PATH


# ============================================================
# BGE-M3 编码（支持多 GPU 分片）
# ============================================================

def _encode_shard(args):
    texts, batch_size, device = args
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(BGE_M3_PATH, device=device)
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=len(texts) > 100,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return np.array(embeddings, dtype=np.float32)


def build_all(corpus_path: str = None, index_dir: str = None,
              devices: list[str] = None, batch_size: int = 256,
              workers: int = None):
    """快速构建所有索引

    Args:
        corpus_path: corpus.json 路径
        index_dir: 索引输出目录
        devices: GPU 设备列表，如 ["cuda:0", "cuda:1"]
                 如果 None 或空列表，则使用 CPU
        batch_size: 编码批量大小（GPU 显存允许范围内越大越好）
        workers: 多进程 workers 数（仅多 GPU 时使用）
    """
    if corpus_path is None:
        from config import DATA_DIR
        corpus_path = os.path.join(DATA_DIR, "corpus.json")
    if index_dir is None:
        from config import INDEX_DIR
        index_dir = INDEX_DIR

    os.makedirs(index_dir, exist_ok=True)

    with open(corpus_path, "r", encoding="utf-8") as f:
        corpus = json.load(f)

    n_chunks = len(corpus)
    texts = [doc["text"] for doc in corpus]
    chunk_ids = [doc["chunk_id"] for doc in corpus]
    chunk_store = {doc["chunk_id"]: doc for doc in corpus}

    print(f"[build_index_fast] Building indexes for {n_chunks} docs...")
    print(f"  devices={devices}, batch_size={batch_size}, workers={workers}")

    # ============================================================
    # 1. FAISS Index（GPU 加速）
    # ============================================================
    print("[build_index_fast] Encoding with BGE-M3...")

    if devices and len(devices) > 0:
        # ---- 多 GPU 分片并行 ----
        n_devices = len(devices)
        chunk_size = (n_chunks + n_devices - 1) // n_devices
        shards = []
        for i in range(n_devices):
            start = i * chunk_size
            end = min((i + 1) * chunk_size, n_chunks)
            if start >= n_chunks:
                break
            shard_texts = texts[start:end]
            shard_device = devices[i % len(devices)]
            shards.append((shard_texts, batch_size, shard_device))
            print(f"  GPU {i}: device={shard_device}, chunks={len(shard_texts)} ({start}~{end})")

        # 并行编码
        all_embeddings = []
        if workers and workers > 1 and len(shards) > 1:
            with ProcessPoolExecutor(max_workers=min(workers, len(shards))) as executor:
                futures = [executor.submit(_encode_shard, s) for s in shards]
                results = [f.result() for f in as_completed(futures)]
            for emb in results:
                all_embeddings.append(emb)
        else:
            for s in shards:
                emb = _encode_shard(s)
                all_embeddings.append(emb)

        # 合并
        embeddings = np.concatenate(all_embeddings, axis=0)
        del all_embeddings

    else:
        # ---- CPU 模式 ----
        print("  CPU mode, batch_size=64 (increase batch_size for speedup)")
        embeddings = _encode_shard((texts, 64, "cpu"))

    dim = embeddings.shape[1]
    print(f"  Encoded {embeddings.shape[0]} vectors, dim={dim}")

    # FAISS IndexFlatIP（内积，encode 已 normalize）
    import faiss
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)
    faiss.write_index(index, os.path.join(index_dir, "faiss.index"))
    print(f"[build_index_fast] FAISS index: {index.ntotal} vectors")

    del embeddings  # 释放显存

    # ============================================================
    # 2. BM25（无需加速，很快）
    # ============================================================
    print("[build_index_fast] Building BM25...")
    from rank_bm25 import BM25Okapi

    # 复用 keyword_search 的分词器
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from retrieval.keyword_search import tokenize
    tokenized = [tokenize(t) for t in texts]
    bm25 = BM25Okapi(tokenized)
    with open(os.path.join(index_dir, "bm25.pkl"), "wb") as f:
        pickle.dump(bm25, f)
    print(f"[build_index_fast] BM25 built for {len(tokenized)} docs")

    # ============================================================
    # 3. chunk_ids + chunk_store
    # ============================================================
    with open(os.path.join(index_dir, "chunk_ids.json"), "w") as f:
        json.dump(chunk_ids, f)
    with open(os.path.join(index_dir, "chunk_store.pkl"), "wb") as f:
        pickle.dump(chunk_store, f)

    print(f"[build_index_fast] All indexes saved to {index_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fast build FAISS + BM25 indexes")
    parser.add_argument("--corpus", default=None, help="Path to corpus.json")
    parser.add_argument("--index-dir", default=None, help="Output index directory")
    parser.add_argument("--devices", default=None,
                        help="GPU devices, e.g. 'cuda:0,cuda:1,cuda:2,cuda:3' (default: CPU)")
    parser.add_argument("--batch-size", type=int, default=256,
                        help="Batch size for encoding (default: 256)")
    parser.add_argument("--workers", type=int, default=None,
                        help="Max parallel processes for multi-GPU (default: num_devices)")
    args = parser.parse_args()

    devices = None
    if args.devices:
        devices = [d.strip() for d in args.devices.split(",")]

    build_all(
        corpus_path=args.corpus,
        index_dir=args.index_dir,
        devices=devices,
        batch_size=args.batch_size,
        workers=args.workers or (len(devices) if devices else None),
    )