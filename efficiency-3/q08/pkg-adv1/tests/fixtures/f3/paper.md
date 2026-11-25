# Sparse-attention state-space forecasting of day-ahead electricity load: an ablation study

> FIXTURE (self-test): synthetic material created for pipeline self-testing. Numbers are internally consistent but this is NOT a real publication and must not be cited as evidence.

## Abstract

We compare a sparse-attention state-space model (SASM) against a seasonal ARIMA baseline and a gradient-boosted tree model for day-ahead electricity load forecasting on 12 regional load series. SASM reduced mean absolute error (MAE) by 18.6% relative to ARIMA and by 9.4% relative to the boosted-tree model. The gain concentrated in the evening peak hours (18:00-21:00), where MAE fell by 24.1%. An ablation removing the sparse bottleneck increased MAE by 7.8%, while removing the calendar covariates increased MAE by only 1.3%. We also report a negative transfer case on one region whose load is dominated by a single industrial customer.

## 1 Introduction

Day-ahead load forecasts feed unit commitment and reserve scheduling. Classical seasonal ARIMA baselines are strong on weekly periodicity but degrade during rapid regime changes such as heat waves. Attention-based models capture long-range dependence but scale poorly with horizon length. We ask whether a sparse-attention bottleneck inside a linear state-space recurrence retains long-horizon accuracy at a fraction of the compute. Our contribution is an ablation that isolates the bottleneck from the calendar and weather covariate blocks.

## 2 Methods

### 2.1 Data and splits

Twelve regional series, hourly resolution, 7 years (61,368 hours per region). Train 5 years, validation 1 year, test 1 year, split chronologically to avoid leakage. Weather covariates: temperature, humidity, and a cooling-degree-hours transform. Calendar covariates: hour-of-day, day-of-week, holiday indicator.

### 2.2 Models

SASM uses 4 layers, hidden size 128, 8 sparse heads with top-k=2 routing, and a 168-hour context window. ARIMA is seasonal with period 24 and 168, selected by AIC. The boosted-tree baseline uses lag features up to 168 hours. All models were trained with the same input window and evaluated on identical test spans, three seeds each.

### 2.3 Metrics

Primary metric: MAE (MW). Secondary: MAPE (%), peak-hour MAE, and training wall-clock time. Differences are reported as relative percentages against ARIMA. We report the mean over three seeds and the standard deviation across seeds.

## 3 Results

### 3.1 Overall accuracy

![Figure 1. Test-set MAE by hour of day for SASM, ARIMA and boosted trees](figures/fig1.png)

SASM achieved a test MAE of 312.4 MW (SD 4.1) versus 383.8 MW (SD 9.7) for ARIMA and 344.7 MW (SD 6.2) for boosted trees. Relative to ARIMA, this is an 18.6% reduction (95% CI 16.9% to 20.3%); relative to boosted trees, 9.4% (95% CI 7.8% to 11.0%). MAPE was 3.42%, 4.21%, and 3.78% respectively.

### 3.2 Where the gain comes from

The improvement is concentrated in the evening peak (18:00-21:00): MAE 289.6 MW versus 381.5 MW for ARIMA, a 24.1% reduction. In overnight hours (01:00-05:00) the models are within 3.2%, and the confidence interval crosses zero. Training SASM took 4.1 GPU-hours versus 0.3 GPU-hours for ARIMA and 1.2 GPU-hours for boosted trees.

### 3.3 Ablation

Removing the sparse bottleneck raised MAE from 312.4 to 336.8 MW (+7.8%). Removing calendar covariates raised MAE by 1.3%; removing weather covariates raised it by 5.6%. In the industrial-dominated region, SASM MAE was 11.2% worse than ARIMA, the only region with a negative relative gain.

## 4 Discussion

The ablation supports the interpretation that the sparse bottleneck, rather than the covariate blocks, drives most of the accuracy gain. The negative transfer case suggests that when a single customer explains most of the variance, long-range attention over-fits recurring patterns that are actually production schedules rather than weather-driven demand.

## 5 Limitations

First, we evaluate on 12 regions from one market; cross-market transfer is untested. Second, the negative transfer region is reported post hoc and was not part of a pre-registered analysis plan. Third, the boosted-tree baseline used default hyperparameters for lag selection, which may understate its accuracy. Fourth, wall-clock comparisons ran on different hardware generations for the GPU models (two of the 12 regions used a slower node). Fifth, the test year included an unusual heat wave, so the magnitude of the peak-hour gain may not replicate in milder years.
