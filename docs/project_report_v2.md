# 用户手册QA对生成数据

## 1. 使用MinerU处理PDF文档
使用MinerU将原始的车辆用户手册PDF解析为json和md数据,并保存在auto文件夹

## 2. 预处理解析数据
将解析后的json数据进一步预处理，包括合并block，过滤掉无caption的图像块，处理table块和图像块为text块格式，以及进行chunk切分，将解析后的json文件进一步处理成适合QA生成的json文件。
```bash
python scripts/mineru_json_to_corpus.py \
    --input auto/ \
    --output data/manuals/corpus.json \
    --chunk-prefix benz_e300 \
    --chunk-size 1200 \
    --overlap 100
```

## 3. 生成index文件
在生成多跳QA对之前，我们首先需要对语料做索引构建，首先生成检索索引。
检索索引生成的文件包含FAISS向量索引生成（faiss.index）和BM25关键词索引（bm25.pkl）生成，同时还生成chunk元数据.
```bash
python scripts/build_index.py \
  --corpus data/manuals/corpus.json \
  --index-dir data/manuals/indexes/
```
接下来生成知识图谱（knowledge_graph.json）和实体向量索引(entity_embeddings.pkl),用于后面多跳QA生成时的三层检索。运行下面脚本前，需要先在llm/clent.py的MODEL_CONFIGS注册DeepSeek-V4-Pro模型。
```bash
python scripts/build_knowledge_graph.py \
  --corpus data/manuals/corpus.json \
  --output-graph data/manuals/indexes/knowledge_graph.json \
  --output-embeddings data/manuals/indexes/entity_embeddings.pkl \
  --model DeepSeek-V4-Pro \
  --workers 20
```

## 4. 数据合成
数据合成需要 3 个步骤，对应 3 个脚本：

**Step 1: 生成种子 QA（原子 QA）**
```bash
python scripts/gen_seed_qa.py \
  --corpus data/manuals/corpus.json \
  --output data/manuals/seeds.jsonl \
  --prompts scripts/synthesis_prompts_vehicle_manual_zh.yaml \
  --model DeepSeek-V4-Flash \
  --workers 20 \
  --limit 400
```
作用：从每个 chunk 生成 3 个原子 QA 对（question + answer）

**Step 2: 多跳合成（核心）**
```bash
python scripts/domain_multihop_synthesis.py \
  --seeds data/manuals/seeds.jsonl \
  --prompts scripts/synthesis_prompts_vehicle_manual_zh.yaml \
  --corpus data/manuals/corpus.json \
  --index-dir data/manuals/indexes/ \
  --output data/manuals/multihop_raw.jsonl \
  --lang zh \
  --model DeepSeek-V4-Flash \
  --merge-model DeepSeek-V4-Flash \
  --num-hop 4 \
  --topk 5 \
  --workers 20
```
作用：从种子 QA 自底向上生成 2-4 跳多跳问题，经过 4 重验证（语义检查、推理检查、单文档检查、全文档检查）

**Step 3: 质量过滤**
```bash
# 1. 规则清洗：去 trivial、去重
python scripts/clean_synthesis.py \
  --input data/manuals/multihop_raw.jsonl \
  --output data/manuals/multihop_clean.jsonl

# 2. LLM judge 打分
python scripts/judge_synthesis.py \
  --input data/manuals/multihop_clean.jsonl \
  --corpus data/manuals/corpus.json \
  --output data/manuals/multihop_judged.jsonl \
  --model DeepSeek-V4-Flash \
  --lang zh \
  --workers 20

# 3. 按 judge 分数过滤
python scripts/judge_synthesis.py \
  --input data/manuals/multihop_judged.jsonl \
  --filter-only \
  --output data/manuals/multihop_final.jsonl
```
作用：过滤低质量合成结果