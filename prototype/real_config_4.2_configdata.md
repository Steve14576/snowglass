# 模型架构图谱 · 依据文件清单

> 用途：记录 `model-atlas` 系列 HTML 中十个模型的每个数字来自哪个文件。
> 结论先说：**架构骨架来自 `config.json`（KB 级），块内的雪花是随机模拟。**
> 没有任何一个块内部的灰度代表真实权重统计。

---

## 0. 文件清单与获取方式

全部为 Hugging Face 官方仓库公开文件，无需登录即可下载 `config.json`。

| 模型 | 仓库 | config 路径 |
|---|---|---|
| Qwen3.5-9B | `Qwen/Qwen3.5-9B` | `config.json` |
| Qwen3.8-27B | `Qwen/Qwen3.8-27B` | `config.json` |
| Qwen3.8-Flash-Next | `Qwen/Qwen3.8-Flash-Next` | `config.json` |
| GLM-5.3-Flash | `zai-org/GLM-5.3-Flash` | `config.json` |
| GPT-OSS-120B | `openai/gpt-oss-120b` | `config.json` |
| RWKV-7 7.2B | `RWKV/RWKV7-7.2B-20260805` | `config.json`（另见模型卡表格） |
| Mamba2-2.7B | `state-spaces/mamba2-2.7b` | `config.json` |
| Jamba-v0.1 | `ai21labs/Jamba-v0.1` | `config.json` |
| Llama-3.1-8B | `meta-llama/Llama-3.1-8B`（镜像 `unsloth/Meta-Llama-3.1-8B`） | `config.json` |
| DeepSeek-V4-Flash-0731 | `deepseek-ai/DeepSeek-V4-Flash-0731` | `config.json` |

**权重文件不参与绘图。** 生成图谱只需要 config；只有当你真的要拿真实权重去降采样时，才需要 `.safetensors` / `.gguf`。

---

## 1. 总览表

| 模型 | 层数 | hidden | FFN/专家中间维 | 词表 | 视觉塔 | 专家数 | 序列混合方式 |
|---|---:|---:|---:|---:|---:|---:|---|
| Qwen3.5-9B | 32 | 4096 | 12288 | 248320 | 27 | — | 24×Linear + 8×Full |
| Qwen3.8-27B | 64 | 5120 | 17408 | 248320 | 27 | — | 48×Linear + 16×Full |
| Qwen3.8-Flash-Next | 48 | 2560 | 640 | 248320 | 27 | 512（top-10） | GDN + QSA + MoE |
| GLM-5.3-Flash | 45 | 4096 | 12288 / 2048 | 154880 | 24 | 288（top-8） | KDA + DSA + MoE |
| GPT-OSS-120B | 36 | 2880 | 2880 | 201088 | — | 128（top-4） | Sliding/Full 交替 + MoE |
| RWKV-7 7.2B | 32 | 4096 | 16384 | 65536 | — | — | TimeMix + ChannelMix |
| Mamba2-2.7B | 64 | 2560 | 0 | 50277 | — | — | 纯 Mamba2 |
| Jamba-v0.1 | 32 | 4096 | 14336 | 65536 | — | 16（top-2） | Mamba + Attn + MoE |
| Llama-3.1-8B | 32 | 4096 | 14336 | 128256 | — | — | 32×Full Attention |
| DeepSeek-V4-Flash-0731 | 43 | 4096 | 2048 | 129280 | — | 256（top-6 + 1 shared） | CSA/HCA + MoE |

---

## 2. 逐模型字段明细

### Qwen3.5-9B

- `architectures`: `Qwen3_5ForConditionalGeneration`
- `text_config.model_type`: `qwen3_5_text`
- `num_hidden_layers`: 32
- `hidden_size`: 4096
- `intermediate_size`: 12288
- `head_dim`: 256 / `num_attention_heads`: 16 / `num_key_value_heads`: 4
- `full_attention_interval`: 4
- `layer_types`: 32 项，`linear_attention, linear_attention, linear_attention, full_attention` 周期重复 8 轮
- `linear_conv_kernel_dim`: 4
- `linear_key_head_dim` / `linear_value_head_dim`: 128 / 128
- `linear_num_key_heads` / `linear_num_value_heads`: 16 / 32
- `vocab_size`: 248320
- `max_position_embeddings`: 262144
- `rope_theta`: 1e7，`partial_rotary_factor`: 0.25
- `tie_word_embeddings`: false
- `mtp_num_hidden_layers`: 1
- `vision_config`: depth 27 / hidden 1152 / intermediate 4304 / heads 16 / patch 16 / spatial_merge 2 / temporal_patch 2 / out_hidden 4096

**可视化映射**：GDN 块内部拆成「输入投影 / 门控·Conv / 输出投影」三代组；Full 层拆 Q-K-V-O，其中 K/V 视觉宽度按 `4/16` 压缩，对应 GQA。

---

### Qwen3.8-27B

同架构，差异字段：

- `num_hidden_layers`: 64
- `hidden_size`: 5120
- `intermediate_size`: 17408
- `num_attention_heads`: 24 / `num_key_value_heads`: 4
- `linear_num_value_heads`: 48
- `vocab_size`: 248320
- `vision_config.out_hidden_size`: 5120

**可视化映射**：64 层必须压缩层高，否则单列过高；默认 `squash` 滑块会给出更矮的层高。

---

### Qwen3.8-Flash-Next

- `text_config.model_type`: `qwen4_exp_text`
- `num_hidden_layers`: 48
- `hidden_size`: 2560
- `num_attention_heads`: 24 / `num_key_value_heads`: 2
- `num_experts`: 512 / `num_experts_per_tok`: 10
- `moe_intermediate_size`: 640
- `shared_expert_intermediate_size`: 640
- `linear_num_key_heads` / `linear_num_value_heads`: 16 / 48
- `ple_embed_dim`: 2560 / `ple_conv_kernel_size`: 4 / `ple_layer_ids`: `[2]`
- `ngram_size`: 3 / `ngram_vocab_size_base`: 20000000 / `split_ngram_parts`: 128
- `mtp_num_hidden_layers`: 1
- `vocab_size`: 248320
- `vision_config`: depth 27 / hidden 1152 / out_hidden 2560

**可视化映射**：每层右侧为 Router + 专家网格（默认聚合 16 格代表 512 个专家）+ 独立共享专家块；第 2 层旁另挂 `PLE / N-gram` 参数表。

**不确定项**：PLE 的真实接入方式与张量命名需读 `modeling_*.py`；图中只表达"存在该参数组"，不表达精确数据流。

---

### GLM-5.3-Flash

- `architectures`: `Glm5NextForConditionalGeneration`
- `model_type`: `glm5_next`
- `num_hidden_layers`: 45
- `hidden_size`: 4096 / `intermediate_size`: 12288
- `layer_types`: 45 项，`linear_attention ×3 + deepseek_sparse_attention ×1`（DSA 位于 3/7/11/.../43）
- `first_k_dense_replace`: 3
- `mlp_layer_types`: 前 3 项 `dense`，其余 42 项 `sparse`
- `num_attention_heads`: 64 / `num_key_value_heads`: 64
- `qk_head_dim` / `v_head_dim`: 256 / 256
- `q_lora_rank`: 1536 / `kv_lora_rank`: 512
- `index_n_heads`: 32 / `index_head_dim`: 128 / `index_topk`: 2048
- `n_routed_experts`: 288 / `num_experts_per_tok`: 8 / `n_shared_experts`: 1
- `moe_intermediate_size`: 2048
- `scoring_func`: sigmoid / `topk_method`: noaux_tc / `routed_scaling_factor`: 2.5
- `hc_mult`: 4 / `mhc`: true
- `vocab_size`: 154880
- 模型卡：320B 总参 / 18B 激活
- `vision_config`: depth 24 / hidden 1024 / intermediate 4096 / patch 14 / image 448 / out_hidden 4096 / projection_intermediate 10240

**可视化映射**：KDA 块拆「QKV 投影 / 逐通道门控·Conv / 输出投影」；DSA 块拆「Q 低秩 / KV 低秩 / Indexer·输出」；前 3 层为 Dense FFN，其余为 Router + 专家网格。

**注意**：`indexer_types` 里的 45 个 `full` 指的是 indexer 类型，**不是**注意力类型，不要混用。

---

### GPT-OSS-120B

- `architectures`: `GptOssForCausalLM`
- `model_type`: `gpt_oss`
- `num_hidden_layers`: 36
- `hidden_size` / `intermediate_size`: 2880 / 2880
- `num_attention_heads`: 64 / `head_dim`: 64 / `num_key_value_heads`: 8
- `num_local_experts`: 128 / `experts_per_token`: 4
- `layer_types`: 36 项，`sliding_attention` 与 `full_attention` 交替
- `sliding_window`: 128
- `vocab_size`: 201088
- `rope_scaling`: yarn，factor 32 / `rope_theta`: 150000
- `quantization_config.quant_method`: `mxfp4`

**可视化映射**：36 层全部为 MoE；每层左侧按 Sliding/Full 交替切换标签与块宽。

---

### RWKV-7 7.2B

- `architectures`: `Rwkv7ForCausalLM`
- `num_hidden_layers`: 32
- `hidden_size`: 4096 / FFN: 16384
- `num_attention_heads`: 64 / head size: 64
- `vocab_size`: 65536
- 训练上下文：16384
- `a_low_rank_dim`: 192 / `decay_low_rank_dim`: 192 / `gate_low_rank_dim`: 384
- 性质：attention-free recurrent，常量大小递归状态

**可视化映射**：每层 = `TimeMix`（含 R/K/V 投影、衰减更新、门控输出）+ `ChannelMix`（Key/Value 两组）。

**重要区分**：图中 TimeMix 是**参数组**，不是运行时 recurrent state。状态是推理时算出来的，不在权重文件里。

---

### Mamba2-2.7B

- `d_model`: 2560
- `d_intermediate`: 0
- `n_layer`: 64
- `vocab_size`: 50277
- `ssm_cfg.layer`: `Mamba2`
- `attn_layer_idx`: `[]`（无 Attention 层）
- `tie_embeddings`: true
- `pad_vocab_size_multiple`: 16

**可视化映射**：每层只有 Mamba2 块，无 Norm2 / 无独立 FFN；词表块与输出共享（图中合并）。

---

### Jamba-v0.1

- `architectures`: `JambaForCausalLM`
- `num_hidden_layers`: 32
- `hidden_size`: 4096 / `intermediate_size`: 14336
- `num_attention_heads`: 32 / `num_key_value_heads`: 8
- `num_experts`: 16 / `num_experts_per_tok`: 2
- `attn_layer_offset`: 4 / `attn_layer_period`: 8 → Attention 在 L4 / L12 / L20 / L28
- `expert_layer_offset`: 1 / `expert_layer_period`: 2 → MoE 在奇数层
- `mamba_d_conv`: 4 / `mamba_d_state`: 16 / `mamba_dt_rank`: 256 / `mamba_expand`: 2
- `vocab_size`: 65536

**可视化映射**：主体按层切换 Mamba / GQA；奇数层叠加专家网格。

**注意**：偶数层是 Dense FFN，奇数层是 MoE。这一点在图上用块的有无直接表达。

---

### Llama-3.1-8B

- `architectures`: `LlamaForCausalLM`
- `model_type`: `llama`
- `num_hidden_layers`: 32
- `hidden_size`: 4096 / `intermediate_size`: 14336
- `num_attention_heads`: 32 / `num_key_value_heads`: 8 / `head_dim`: 128
- `vocab_size`: 128256
- `rope_theta`: 500000 / `rope_scaling`: llama3, factor 8
- `tie_word_embeddings`: false

**可视化映射**：最干净的对照组：32 层，每层 = Norm1 + GQA + Norm2 + SwiGLU。

---

### DeepSeek-V4-Flash-0731

- `architectures`: `DeepseekV4ForCausalLM`
- `model_type`: `deepseek_v4`
- `num_hidden_layers`: 43
- `hidden_size`: 4096
- `num_attention_heads`: 64 / `head_dim`: 512 / `num_key_value_heads`: 1
- `q_lora_rank`: 1024 / `o_lora_rank`: 1024 / `o_groups`: 8 / `qk_rope_head_dim`: 64
- `n_routed_experts`: 256 / `num_experts_per_tok`: 6 / `n_shared_experts`: 1
- `moe_intermediate_size`: 2048
- `index_n_heads`: 64 / `index_head_dim`: 128 / `index_topk`: 512
- `hc_mult`: 4 / `hc_sinkhorn_iters`: 20
- `compress_ratios`: 46 项，`0,0,4,128,4,128,...,0,0,0`
- `num_hash_layers`: 3
- `num_nextn_predict_layers`: 1
- `dspark_target_layer_ids`: `[40,41,42]`
- `sliding_window`: 128
- `vocab_size`: 129280 / `max_position_embeddings`: 1048576
- `quantization_config`: fp8, weight_block_size 128×128

**可视化映射**：按 `compress_ratios` 的 0 / 4 / 128 三档区分注意力块宽度；每层 MoE 块 + 独立共享专家。

**不确定项**：`compress_ratios` 长度为 46 与 `num_hidden_layers` 43 不完全对齐，真实对应关系要读 `modeling_deepseek_v4.py`。图中按"偶数层 CSA、奇数层 HCA"近似，属**示意**，不是精确层表。

---

## 3. 图中"不来自 config"的部分

必须和甲方/观众讲清楚，避免被当成真实计算图：

| 图中元素 | 状态 |
|---|---|
| 层数、hidden、FFN、词表、专家数、注意力类型周期 | **来自 config / 模型卡** |
| 块的三维尺寸、位置、间距、压扁比 | **可视化设计**，非真实比例 |
| 块内雪花点的位置与亮度 | **随机数生成**，与真实权重无统计关系 |
| 独立"专家库"侧栏 | **已移除**，改为每层就地展示专家 |
| 残差连线 | **不画**（按需求） |
| KV Cache、logits、next token | **不画**（运行时产物，不是权重） |
| PLE 接入位置、DSpark 具体路径 | **仅示意**，需读 modeling 代码 |
| DeepSeek compress_ratios 与层的精确对应 | **近似** |

---

## 4. 若要接真实权重，需要补什么

每个块的行为，最终对应权重文件里的**一组张量名**。例如 Llama-3.1-8B：

```text
model.embed_tokens.weight            [128256, 4096]
model.layers.{i}.input_layernorm.weight        [4096]
model.layers.{i}.self_attn.q_proj.weight       [4096, 4096]
model.layers.{i}.self_attn.k_proj.weight       [1024, 4096]
model.layers.{i}.self_attn.v_proj.weight       [1024, 4096]
model.layers.{i}.self_attn.o_proj.weight       [4096, 4096]
model.layers.{i}.post_attention_layernorm.weight [4096]
model.layers.{i}.mlp.gate_proj.weight          [14336, 4096]
model.layers.{i}.mlp.up_proj.weight            [14336, 4096]
model.layers.{i}.mlp.down_proj.weight          [4096, 14336]
model.norm.weight                    [4096]
lm_head.weight                       [128256, 4096]