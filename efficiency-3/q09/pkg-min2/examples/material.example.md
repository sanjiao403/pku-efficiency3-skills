# 示例材料（合成，非真实论文）

We study whether sparse mixture routing can cut retrieval latency without hurting
answer quality on long-context question answering. On our held-out benchmark the
proposed router reduces p95 latency by 41.2% while accuracy drops by only 0.8
points, from 72.5 to 71.7. All experiments use the same encoder and the same
retrieval budget of 32 passages, so the comparison isolates the routing change.

## 1 Introduction

## 2 Method

The router is a two-layer transformer over passage summaries, trained with a
listwise objective. For each query we score 256 candidate passages, keep the top 32
by router logit, and pass only those to the reader. The reader is unchanged from
the dense baseline, and both stages share the same encoder weights. Training uses
8 GPUs for 36 hours with a batch size of 64 and a learning rate of 3e-5.

## 3 Results

On the held-out benchmark the router reaches 71.7 accuracy against 72.5 for the
dense baseline, while p95 latency falls from 940 ms to 553 ms. The ablation without
the listwise objective loses 3.1 points, which suggests that the training signal
matters more than the router capacity. A second ablation that keeps 16 passages
instead of 32 loses 1.4 points and saves another 120 ms.

## 4 Limitations
