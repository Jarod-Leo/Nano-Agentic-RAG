# AGENT.md

## Purpose

This repository contains an Agentic RAG system for multi-hop QA, plus the surrounding data synthesis, SFT, and GRPO training pipeline.

The code in `core/` is the project-specific layer. The directories `LLaMA-Factory/` and `verl/` are bundled training frameworks and should be treated as external dependencies unless a task explicitly requires changing them.

## Repo Map

### Core runtime

- `config.py`: global paths, model names, retrieval defaults, and environment variable overrides. Importing this file creates several directories such as `results/` and `tmp/`.
- `agents/`: LangGraph orchestration for the online QA agent.
  - `router.py`: classifies a query as `simple` or `multi_hop`.
  - `planner.py`: decomposes a multi-hop question into retrieval steps.
  - `executor.py`: runs retrieval tools and records evidence.
  - `verifier.py`: decides whether evidence is sufficient or whether replanning is needed.
  - `synthesizer.py`: turns evidence into the final answer.
  - `graph.py`: builds the full graph and exposes `run_query(...)`.
  - `prompts.py`: prompt templates, model-size profiles, language switching, and retrieval/iteration budgets.
- `retrieval/`: retrieval implementations.
  - `semantic_search.py`: dense retrieval.
  - `keyword_search.py`: BM25 keyword retrieval.
  - `graph_search.py`: graph-based traversal retrieval.
  - `hybrid_search.py`: parallel multi-tool fusion via RRF + rerank.
  - `read_chunk.py`: fetch by `chunk_id`.
  - `embedder.py` and `reranker.py`: BGE wrapper layers.
- `llm/client.py`: unified OpenAI-compatible client for local vLLM and remote APIs.
- `api/server.py`: FastAPI demo server exposing `/query` and `/health`.

### Evaluation and scripts

- `evaluation/run_eval.py`: main evaluation entry point. Loads QA pairs, runs the graph, saves checkpoints/results, and can enable LLM judge metrics.
- `evaluation/metrics.py`, `evaluation/hop_aware_eval.py`, `evaluation/llm_judge.py`: metrics and diagnostics.
- `scripts/run_pipeline.py`: simplest end-to-end smoke test for a single query.
- `scripts/eval_agentic.py` and `scripts/run_cloud_eval.py`: project evaluation scripts used in the README workflow.
- `scripts/build_index.py`, `scripts/build_knowledge_graph.py`: offline retrieval asset construction.
- `scripts/domain_multihop_synthesis.py` and related synthesis scripts: data generation / cleaning / conversion pipeline.

### Training

- `training/sft_pipeline.sh`: SFT workflow around `LLaMA-Factory/`.
- `training/start_retrieval_server.sh`: retrieval service used during GRPO rollouts.
- `training/start_grpo.sh`: GRPO training launcher around `verl/`.
- `training/reward_agentic_rag.py`: project reward function logic.
- `training/config/` and `training/tools/`: GRPO-side configs and tool implementations.

### Data and generated outputs

- `data/`: datasets, evaluation files, indexes, traces, and derived training artifacts.
- `results/`: evaluation outputs. Created automatically by `config.py`.
- `tmp/`: scratch directory. Created automatically by `config.py`.

## How To Work In This Repo

### 1. Start with the narrowest entry point

- For answer-generation bugs, start in `agents/graph.py` and the node mentioned in the failing trace.
- For retrieval quality issues, inspect `retrieval/` plus `agents/executor.py`.
- For prompt behavior, inspect `agents/prompts.py` together with the node that consumes the prompt.
- For model endpoint issues, inspect `llm/client.py` and environment variables before editing application logic.
- For evaluation regressions, reproduce with `evaluation/run_eval.py` or `scripts/run_pipeline.py` before touching training code.

### 2. Prefer changing project code, not vendored frameworks

Only modify `LLaMA-Factory/` or `verl/` when the task is explicitly about those frameworks. Most project-specific behavior lives under `agents/`, `retrieval/`, `llm/`, `evaluation/`, `scripts/`, and `training/`.

### 3. Keep the state flow consistent

The LangGraph state is defined in `agents/state.py`. The important fields are:

- `plan`: planner output.
- `evidence`: accumulated retrieval evidence across steps.
- `tool_calls`: retrieval call log.
- `verification_result` and `verification_feedback`: verifier output for replanning.
- `final_answer`: synthesizer output.
- `trace`: execution trace used by scripts and debugging.

If you add a new node or change a node contract, update the state shape and every downstream consumer that reads that field.

## Important Implementation Notes

### Prompt profiles are model-size and language dependent

`agents/prompts.py` chooses a profile based on:

- model name pattern: small vs large profile.
- `config.PROMPT_LANG`: `zh` uses Chinese prompts, otherwise English.

The current budgets are encoded in the prompt profile, not in `graph.py`:

- small profiles: `max_iterations = 3`, `max_retrieval_calls = 10`
- large profiles: `max_iterations = 5`, `max_retrieval_calls = 15`

If you change routing/planning/verifying behavior, check whether the prompt profile or budget should change too.

### Tool registration is split across planner and executor

If you add or remove a retrieval tool, update at least:

- the implementation in `retrieval/`
- `_ensure_tools()` in `agents/executor.py`
- `TOOL_DESCRIPTIONS` in `agents/planner.py`

If the planner prompt depends on the tool list format, verify the prompt output still parses into valid JSON.

### `evaluation/run_eval.py` mutates config at runtime

The evaluator can override:

- `config.AGENT_LLM_MODEL`
- `config.PROMPT_LANG`
- `config.ACTIVE_INDEX_DIR`
- `llm.client.AGENT_LLM_MODEL`

Because of this, prefer using CLI args or environment variables for experiments instead of hardcoding temporary values into `config.py`.

### Retrieval models are lazily loaded

Embedding and reranking models are loaded through wrappers in `retrieval/embedder.py` and `retrieval/reranker.py`. `evaluation/run_eval.py` may monkey-patch device selection to pre-load them onto a selected GPU. Be careful when refactoring these helper functions because evaluation depends on that behavior.

## Environment And Commands

This repo expects two environments:

- `agenticrag` for inference, evaluation, synthesis, and SFT preparation.
- `verl` for GRPO training and rollout infrastructure.

Common commands from the repository root:

```bash
python scripts/run_pipeline.py "Were Scott Derrickson and Ed Wood of the same nationality?"
python evaluation/run_eval.py --max-samples 20 --workers 1
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
bash training/start_retrieval_server.sh
bash training/sft_pipeline.sh
bash training/start_grpo.sh
```

Important environment variables used throughout the repo:

- `MODEL_HUB`
- `BGE_M3_PATH`
- `BGE_RERANKER_PATH`
- `AGENT_LLM_MODEL`
- `PROMPT_LANG`
- `VLLM_BASE_URL`
- `VLLM_32B_URL`
- `JUDGE_BASE_URL`
- `JUDGE_LLM_MODEL`
- `NEWS_CORPUS_DIR`
- `NEWS_INDEX_DIR`

When debugging model failures, inspect these variables before assuming the Python logic is wrong.

## Validation Expectations

There is no small dedicated unit-test suite in the project-specific root code. Validation is mostly script-driven.

Prefer the lightest useful check:

- For agent logic changes: run `python scripts/run_pipeline.py "<query>"`.
- For retrieval changes: run a targeted query through the pipeline and inspect `trace` / `evidence`.
- For evaluation logic changes: run `python evaluation/run_eval.py --max-samples 5`.
- For API changes: start `api/server.py` or `uvicorn` and hit `/health`.
- For training-script edits: verify shell variable wiring and referenced file paths before running long jobs.

If you cannot run a heavy pipeline locally, explain what remains unverified.

## Safe Change Guidelines

- Do not hand-edit generated outputs in `results/` or transient files in `tmp/` unless the task is specifically about artifacts.
- Avoid large formatting-only edits in prompt files or training shell scripts; small text changes can materially affect behavior.
- Preserve JSON output contracts expected by `agent_chat_json(...)` callers in `router.py`, `planner.py`, and `verifier.py`.
- Keep answer post-processing in `agents/synthesizer.py` consistent with the prompt format. If you change the output tags or prefixes, update `_extract_short_answer(...)`.
- Be cautious with shell scripts under `training/`: they assume specific environment names, services, and GPU topology.

## Recommended First Reads For New Tasks

For most tasks, read these files first:

1. `README.md`
2. `config.py`
3. `agents/graph.py`
4. `agents/prompts.py`
5. The module closest to the bug or requested feature

That sequence is usually enough to understand whether a change belongs in orchestration, retrieval, prompting, evaluation, or training.
