# Qwen3.5-9B（Q4_K_M GGUF）模型事实表

本文件只记"这个模型文件里实际有什么"，全部来自脚本实测，每一条都写了是怎么得到的。
要做什么、怎么做，不在这里，在 `docs/decisions.md`。

## 1. 文件

| 文件 | 内容 | 大小 | sha256（与 HuggingFace 记录一致） |
|---|---|---|---|
| `data/gguf/Qwen3.5-9B-Q4_K_M.gguf` | 文本部分 | 5,680,522,464 字节 | `03b74727…52b7e8` |
| `data/gguf/mmproj-BF16.gguf` | 视觉塔 | 921,705,024 字节 | `853698ce…a83383` |

来源：`unsloth/Qwen3.5-9B-GGUF`，仓库版本 `3885219b68`，下载脚本 `scripts/download_gguf.py`。
完整张量清单（名字、形状、量化类型、元素数、字节数）：`out/inventory/Qwen3.5-9B-Q4_K_M.tensors.json`、`out/inventory/mmproj-BF16.tensors.json`，由 `scripts/gguf_inventory.py` 生成。

## 2. 文本部分的关键参数

读自 GGUF 文件头的元数据（`general.architecture = qwen35`）：

| 字段 | 值 | 含义 |
|---|---|---|
| block_count | 32 | 32 层 |
| embedding_length | 4096 | 残差流 x 的宽度，也就是残差棒代表的那个向量的维数 |
| feed_forward_length | 12288 | MLP 中间层宽度，是 4096 的 3 倍 |
| full_attention_interval | 4 | 每 4 层一个全注意力层，其余是线性注意力（GDN） |
| attention.head_count / head_count_kv | 16 / 4 | 全注意力层：16 个 query 头，4 个 key/value 头（4 个 query 头共用一组 key/value） |
| attention.key_length / value_length | 256 / 256 | 全注意力层每个头 256 维 |
| rope.dimension_count | 64 | 位置编码只转每个头 256 维里的前 64 维，即 25 % |
| ssm.group_count | 16 | 线性注意力层：key 头数 |
| ssm.state_size | 128 | 线性注意力层：每头维度 |
| ssm.time_step_rank | 32 | 线性注意力层：value 头数 |
| ssm.inner_size | 4096 | 线性注意力层：value 总宽度 = 32 头 × 128 |
| ssm.conv_kernel | 4 | 线性注意力层：短卷积长度 |
| 词表（tokenizer.ggml.tokens） | 248,320 | |
| context_length | 262,144 | |

## 3. 张量统计

共 427 个张量，8.954 B 个参数。

| 存储格式 | 张量数 | 字节 | 用在哪 |
|---|---|---|---|
| Q4_K | 132 | 3.316 GB | 大部分矩阵 |
| Q6_K | 22 | 1.512 GB | lm_head、一半的 ffn_down、多数 attn_v |
| Q5_K | 48 | 0.830 GB | 线性注意力层的 attn_qkv 与 ssm_out |
| Q8_0 | 48 | 0.007 GB | 线性注意力层的 ssm_alpha、ssm_beta |
| F32 | 177 | 0.004 GB | 所有一维张量和 ssm_conv1d |

按张量种类细分（层号见 tensors.json）：

| 张量 | 存储格式 |
|---|---|
| ffn_down | Q6_K 16 层，Q4_K 16 层 |
| attn_v | Q6_K 5 层，Q4_K 3 层 |
| ffn_gate、ffn_up、attn_gate、attn_q、attn_k、attn_output、token_embd | 全部 Q4_K |
| attn_qkv、ssm_out | 全部 Q5_K |
| output（lm_head） | Q6_K |

"Q4_K_M"是这套混合配方的名字，不是说每个张量都是 4 bit。manifest 必须按张量记录实际格式。

**和 HF 原版对账**：HF safetensors 共 775 个张量，其中视觉塔 333 个，文本部分 442 个。GGUF 文本部分是 427 个，少 15 个。
按每层的张量数核算：线性注意力层每层 14 个 × 24 层 + 全注意力层每层 11 个 × 8 层 + embed、lm_head、最终 norm 共 3 个 = 427，正好对上。差的 15 个是 HF 里以 `mtp.` 开头的多 token 预测头（MTP）。
所以 **GGUF 版没有 MTP 头**。这个结论是按数目对账推出来的，没有逐个列出 HF 的 MTP 张量核对。

## 4. 两种层的组成，以及与 HF 名字的对照

32 层只有两种组成（`scripts/gguf_inventory.py` 按每层张量名归类得出）：

- 线性注意力层（GDN）：第 0、1、2、4、5、6、8 … 层，共 24 层
- 全注意力层：第 3、7、11、15、19、23、27、31 层，共 8 层

形状按行优先写，与 HF 写法一致。"作用"一栏是按这类结构的通常写法理解的，没有逐行核对 Qwen3.5 的 modeling 代码。

### 线性注意力层（以第 0 层为例）

| GGUF 名 | HF 名（前缀 `model.language_model.layers.0.`） | 形状 | 格式 | 作用 |
|---|---|---|---|---|
| attn_norm.weight | input_layernorm.weight | [4096] | F32 | 层入口 RMSNorm，存值 = HF + 1（见第 5 节） |
| attn_qkv.weight | linear_attn.in_proj_qkv.weight | [8192, 4096] | Q5_K | 一次算出 q、k、v。行 0–2047 是 q（16 头 × 128），2048–4095 是 k（16 头 × 128），4096–8191 是 v（32 头 × 128） |
| attn_gate.weight | linear_attn.in_proj_z.weight | [4096, 4096] | Q4_K | 输出门控（32 头 × 128） |
| ssm_alpha.weight | linear_attn.in_proj_a.weight | [32, 4096] | Q8_0 | 每个 value 头一行 |
| ssm_beta.weight | linear_attn.in_proj_b.weight | [32, 4096] | Q8_0 | 每个 value 头一行 |
| ssm_conv1d.weight | linear_attn.conv1d.weight | [8192, 4] | F32 | 对 q、k、v 共 8192 个通道各做一个长度 4 的短卷积 |
| ssm_a | linear_attn.A_log | [32] | F32 | 每个 value 头一个数，存值 = −exp(HF 值) |
| ssm_dt.bias | linear_attn.dt_bias | [32] | F32 | 每个 value 头一个数 |
| ssm_norm.weight | linear_attn.norm.weight | [128] | F32 | 按每头 128 维做的 norm，原样保存 |
| ssm_out.weight | linear_attn.out_proj.weight | [4096, 4096] | Q5_K | 输出投影，列 = 32 头 × 128 |
| post_attention_norm.weight | post_attention_layernorm.weight | [4096] | F32 | MLP 前的 RMSNorm，存值 = HF + 1 |
| ffn_gate.weight | mlp.gate_proj.weight | [12288, 4096] | Q4_K | |
| ffn_up.weight | mlp.up_proj.weight | [12288, 4096] | Q4_K | |
| ffn_down.weight | mlp.down_proj.weight | [4096, 12288] | 第 0 层 Q6_K | |

### 全注意力层（以第 3 层为例）

| GGUF 名 | HF 名（前缀 `model.language_model.layers.3.`） | 形状 | 格式 | 作用 |
|---|---|---|---|---|
| attn_norm.weight | input_layernorm.weight | [4096] | F32 | 存值 = HF + 1 |
| attn_q.weight | self_attn.q_proj.weight | [8192, 4096] | Q4_K | 16 头 × 512。8192 是 16 × 256 的两倍，多出的一半推断是输出门控（从形状推断，未核对代码） |
| attn_k.weight | self_attn.k_proj.weight | [1024, 4096] | Q4_K | 4 个 key 头 × 256 |
| attn_v.weight | self_attn.v_proj.weight | [1024, 4096] | 第 3 层 Q6_K | 4 个 value 头 × 256 |
| attn_q_norm.weight | self_attn.q_norm.weight | [256] | F32 | 存值 = HF + 1 |
| attn_k_norm.weight | self_attn.k_norm.weight | [256] | F32 | 未单独核对，按 q_norm 推断同样 + 1 |
| attn_output.weight | self_attn.o_proj.weight | [4096, 4096] | Q4_K | 列 = 16 头 × 256 |
| post_attention_norm.weight | post_attention_layernorm.weight | [4096] | F32 | 存值 = HF + 1 |
| ffn_gate / ffn_up / ffn_down | mlp.gate_proj / up_proj / down_proj | 同上 | | |

### 不属于任何层的

| GGUF 名 | HF 名 | 形状 | 格式 |
|---|---|---|---|
| token_embd.weight | model.language_model.embed_tokens.weight | [248320, 4096] | Q4_K |
| output.weight | lm_head.weight | [248320, 4096] | Q6_K |
| output_norm.weight | model.language_model.norm.weight | [4096] | F32，存值 = HF + 1 |

embed 和 lm_head 是两份独立的权重，不共用。

## 5. GGUF 与 HF 原版的约定差异（实测）

以下都是把 GGUF 里的值和从 HF 用 Range 取来的 BF16 原值逐元素比对得出的。

**维度顺序**：GGUF 记录形状时最快变化的维度在前，反转之后与 HF 的 [行, 列] 完全一致，不需要转置。
证据：`scripts/verify_gguf_decode.py`，见第 6 节的相关系数。

**norm 权重加了 1**：HF 里 RMSNorm 的权重存的是"相对 1 的偏移量"，llama.cpp 转换时把 1 加了进去。
证据：`scripts/verify_gguf_1d.py`。第 0 层 input_layernorm、post_attention_layernorm，第 3 层 q_norm，最终 norm，四处的最大差都是 0（或 6×10⁻⁸）。线性注意力层内部的 ssm_norm 没有加 1，原样保存。

**A_log 被换成了 −exp(A_log)**，同时按下面的规则重排。

**线性注意力的 32 个 value 头被重新排序**：
- 规则：GGUF 第 j 个 value 头 = HF 第 p[j] 个，p[j] = (j mod 16) × 2 + ⌊j / 16⌋。也就是 GGUF 前 16 个依次是 HF 的 0、2、4 … 30 号，后 16 个是 1、3 … 31 号。
- 严格验证：按这个规则重排后，dt_bias 的最大差为 0，ssm_a 与 −exp(A_log) 的最大差为 4×10⁻⁹。另外两个候选规则（不重排；p[j] = ⌊j/2⌋ + (j mod 2) × 16）都不成立。
- 涉及的张量：ssm_alpha、ssm_beta、attn_gate、ssm_out（按列）、attn_qkv 的 v 段（行 4096–8191）、ssm_conv1d 的 v 通道、ssm_a、ssm_dt.bias。每个头分块后与 HF 对应块的相关系数都在 0.997 到 1.000 之间。
- 不涉及：attn_qkv 的 q 段和 k 段、ssm_conv1d 的 q 通道，都保持原顺序。
- 这样重排不改变模型的计算结果（头的顺序本来就可以任意交换）。llama.cpp 为什么这样排，没有核实。
- 只验证了第 0 层。转换脚本对所有层用同一套逻辑，其余 23 个线性注意力层应当相同，但没有逐层核对。
- 证据：`scripts/verify_gguf_gdn_order.py`。

## 6. 真实解码误差（相对 HF 的 BF16 原版）

| 张量 | 格式 | 逐元素相关系数 | 误差均方根 / σ | 最大绝对误差（σ） |
|---|---|---|---|---|
| blk.3.attn_q（= layers.3.self_attn.q_proj） | Q4_K | 0.9973 | 7.4 % | 0.0170（σ = 0.0185） |
| blk.0.ffn_down（= layers.0.mlp.down_proj） | Q6_K | 0.99983 | 1.8 % | 0.0096（σ = 0.0110） |

解码用的是 `gguf` 包（0.19.0）的 `quants.dequantize`，已确认支持本文件用到的全部 5 种格式。
对照：此前 U5 用自写的"每 32 个权重共用一个缩放系数"模拟 Q4，在 down_proj 上得到的误差是 9.9 %；真实 Q4_K 更准。另外 down_proj 在这个文件里实际是 Q6_K。
证据：`scripts/verify_gguf_decode.py`。

## 7. 视觉塔（mmproj-BF16.gguf）

元数据（`general.architecture = clip`）：

| 字段 | 值 | 含义 |
|---|---|---|
| clip.vision.block_count | 27 | 27 层 |
| clip.vision.embedding_length | 1152 | 视觉塔内部宽度 |
| clip.vision.feed_forward_length | 4304 | 视觉塔 MLP 中间层宽度 |
| clip.vision.attention.head_count | 16 | |
| clip.vision.patch_size / image_size | 16 / 768 | 图像切成 16×16 像素的小块 |
| clip.vision.spatial_merge_size | 2 | 相邻 2×2 个小块合并后再送进语言模型 |
| clip.vision.projection_dim | 4096 | 输出宽度，等于语言模型的 4096 |
| clip.projector_type | qwen3vl_merger | |
| clip.vision.is_deepstack_layers | 27 个值全部为 False | 没有视觉层把中间结果直接送进语言模型的中间层；视觉只在输入端接入 |

张量：334 个，0.456 B 个参数；BF16 110 个（0.902 GB），F32 224 个。
每层 12 个张量，27 层组成相同：attn_qkv（[3456, 1152]，即 3 × 1152）、attn_out、ffn_up、ffn_down 的权重和偏置，以及 ln1、ln2 的权重和偏置。
不属于任何层的：
- `v.patch_embd.weight` 与 `v.patch_embd.weight.1`，各 [1152, 3, 16, 16]，F32。推测是 HF 里时间维为 2 的一个卷积被拆成了两个（HF 视觉塔 333 个张量，这里 334 个，多出的正是这一个），未核对 HF 原形状。
- `v.position_embd.weight` [2304, 1152]（2304 = 48 × 48）
- `v.post_ln` 的权重和偏置
- 投影器 `mm.0`（[4608, 4608]）与 `mm.2`（[4096, 4608]），4608 = 1152 × 4，对应 2×2 合并

视觉塔的精度是 BF16，不是 Q4；与文本部分混在一个作品里时，manifest 要分别记录。

## 8. 相关脚本

| 脚本 | 做什么 |
|---|---|
| `scripts/download_gguf.py` | 下载两个文件，按 HF 记录的 sha256 校验 |
| `scripts/gguf_inventory.py` | 读文件头，输出元数据、量化统计、每层组成，写出 tensors.json |
| `scripts/verify_gguf_decode.py` | 解码两个二维张量，与 HF BF16 逐元素比对 |
| `scripts/verify_gguf_1d.py` | 比对一维张量的数值约定；读视觉塔的 is_deepstack_layers |
| `scripts/verify_gguf_gdn_order.py` | 求出并验证线性注意力 value 头的重排规则 |
