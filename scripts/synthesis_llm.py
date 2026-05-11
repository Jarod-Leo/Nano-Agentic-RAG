from __future__ import annotations

"""LLM 调用封装：用于多跳 QA 合成 pipeline，基于 mog-1 (GPT-5) via KS API"""
import json
import re
import time
import threading
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # 项目根目录

logger = logging.getLogger("synthesis")

# ---------- 全局统计 ----------
_stats_lock = threading.Lock()
_stats = {
    "calls": 0,
    "errors": 0,
    "total_latency": 0.0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "cached_tokens": 0,
    "calls_with_usage": 0,
    "by_model": {},
}
_thread_stats = threading.local()

# ---------- 并发控制 ----------
_semaphore = None


def init_concurrency(max_concurrent: int = 20):
    """初始化并发信号量"""
    global _semaphore
    _semaphore = threading.Semaphore(max_concurrent)


def get_stats() -> dict:
    with _stats_lock:
        stats = dict(_stats)
        stats["by_model"] = {model: dict(values) for model, values in _stats["by_model"].items()}
        return stats


def reset_stats():
    with _stats_lock:
        for key in _stats:
            if key == "by_model":
                _stats[key] = {}
            else:
                _stats[key] = 0.0 if key == "total_latency" else 0


def _empty_usage_stats() -> dict:
    return {
        "calls": 0,
        "errors": 0,
        "total_latency": 0.0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cached_tokens": 0,
        "calls_with_usage": 0,
        "by_model": {},
    }


def begin_seed_stats():
    """Start per-thread LLM stats for one seed item."""
    _thread_stats.current = _empty_usage_stats()


def end_seed_stats() -> dict:
    """Finish and return per-thread LLM stats for one seed item."""
    current = getattr(_thread_stats, "current", None)
    _thread_stats.current = None
    if current is None:
        return _empty_usage_stats()
    result = dict(current)
    result["by_model"] = {model: dict(values) for model, values in current.get("by_model", {}).items()}
    return result


def _get_nested_int(data: dict, paths: list[tuple[str, ...]]) -> int:
    for path in paths:
        cur = data
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                cur = None
                break
            cur = cur[key]
        if isinstance(cur, int):
            return cur
    return 0


def _extract_usage_counts(usage: dict | None) -> dict:
    usage = usage or {}
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
    cached_tokens = _get_nested_int(usage, [
        ("prompt_tokens_details", "cached_tokens"),
        ("input_tokens_details", "cached_tokens"),
        ("input_token_details", "cache_read"),
        ("usage", "prompt_tokens_details", "cached_tokens"),
    ])
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cached_tokens": cached_tokens,
        "calls_with_usage": 1 if usage else 0,
    }


def _add_counts(target: dict, counts: dict):
    for key, value in counts.items():
        target[key] = target.get(key, 0) + value


def _add_model_counts(stats: dict, model: str, latency: float, error: bool, usage_counts: dict):
    by_model = stats.setdefault("by_model", {})
    model_stats = by_model.setdefault(model, _empty_usage_stats())
    model_stats["calls"] += 1
    model_stats["total_latency"] += latency
    _add_counts(model_stats, usage_counts)
    if error:
        model_stats["errors"] += 1


def _record_call(model: str, latency: float, error: bool = False, usage: dict | None = None):
    usage_counts = _extract_usage_counts(usage)
    with _stats_lock:
        _stats["calls"] += 1
        _stats["total_latency"] += latency
        _add_counts(_stats, usage_counts)
        if error:
            _stats["errors"] += 1
        _add_model_counts(_stats, model, latency, error, usage_counts)
    current = getattr(_thread_stats, "current", None)
    if current is not None:
        current["calls"] += 1
        current["total_latency"] += latency
        _add_counts(current, usage_counts)
        if error:
            current["errors"] += 1
        _add_model_counts(current, model, latency, error, usage_counts)


# ---------- JSON 解析 ----------
def _clean_json_block(text: str) -> str:
    return text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()


def _extract_json(text: str):
    """从 LLM 回复中提取 JSON"""
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 尝试找 [] 或 {}
    for start_c, end_c in [('[', ']'), ('{', '}')]:
        idx_s = text.find(start_c)
        idx_e = text.rfind(end_c)
        if idx_s != -1 and idx_e > idx_s:
            try:
                return json.loads(text[idx_s:idx_e + 1])
            except json.JSONDecodeError:
                continue
    return None


# ---------- 核心调用 ----------
def llm_call(prompt: str, model: str = "gpt-oss-120b", temperature: float = 0.7,
             system_prompt: str = "You are a helpful assistant.",
             timeout: int = 200) -> str:
    """单次 LLM 调用（带并发控制，统一走 llm.client）"""
    sem = _semaphore
    if sem:
        sem.acquire()
    try:
        t0 = time.time()
        from llm.client import get_from_llm
        resp = get_from_llm(prompt, model_name=model, temperature=temperature, return_usage=True)
        usage = None
        if isinstance(resp, tuple):
            resp, usage = resp
        _record_call(model, time.time() - t0, usage=usage)
        return resp or ""
    except Exception as e:
        _record_call(model, time.time() - t0 if 't0' in dir() else 0, error=True)
        raise
    finally:
        if sem:
            sem.release()


def llm_call_with_retry(prompt: str, max_retries: int = 3,
                        model: str = "mog-1", temperature: float = 0.7,
                        return_json: bool = False,
                        timeout: int = 200) -> str | dict | list | None:
    """带重试的 LLM 调用，可选 JSON 解析"""
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = llm_call(prompt, model=model, temperature=temperature, timeout=timeout)
            if return_json:
                parsed = _extract_json(resp)
                if parsed is not None:
                    return parsed
                # JSON 解析失败，重试
                logger.warning(f"JSON parse failed (attempt {attempt+1}), raw: {resp[:200]}")
                last_error = ValueError(f"JSON parse failed: {resp[:200]}")
                time.sleep(1)
                continue
            return resp
        except Exception as e:
            last_error = e
            logger.warning(f"LLM call failed (attempt {attempt+1}/{max_retries}): {e}")
            time.sleep(2 * (attempt + 1))

    if return_json:
        logger.error(f"All {max_retries} retries failed for JSON call: {last_error}")
        return None
    raise RuntimeError(f"LLM call failed after {max_retries} retries: {last_error}")


def llm_judge(question: str, golden_answer: str, other_answer: str,
              judge_prompt: str, model: str = "mog-1") -> dict:
    """EssEq 评分：判断 other_answer 是否等价于 golden_answer"""
    prompt = f"Input:\nQuestion: {question}\nGolden answer: {golden_answer}\nOther answer: {other_answer}"
    result = llm_call_with_retry(
        prompt=f"{judge_prompt}\n\n{prompt}",
        model=model,
        return_json=True,
        max_retries=2,
    )
    if result is None:
        return {"avg_score": 0, "reasons": [], "raw_scores": []}
    if isinstance(result, list):
        result = result[0] if result else {}
    return {
        "avg_score": result.get("answer_score", 0),
        "reasons": [result.get("answer_reason", "")],
        "raw_scores": [result.get("answer_score", 0)],
    }
