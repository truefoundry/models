# Model benchmarks

This directory mirrors the relative paths of model files in `providers/`: every
provider model file has a benchmark file with the same name and sub-path. Each
file contains:

- `model`: the provider model name;
- `artificial_analysis_id` and `artificial_analysis_slug`: the repository's
  Artificial Analysis match, when one exists; and
- `metrics`, grouped by source. `metrics: {}` means no source publishes
  benchmark data for the model, or the model is not listed on OpenRouter.

Metric sub-sections:

- `artificial_analysis`: metrics from the Artificial Analysis Free Data API,
  merged with the Artificial Analysis evaluations shown on the model's
  OpenRouter page (`https://openrouter.ai/<model>#benchmarks`). Metric names
  drop the `artificial_analysis_` prefix. Free Data API values take precedence;
  OpenRouter values fill metrics the Free Data API leaves `null`. Image, video,
  and speech models report arena Elo fields instead. When OpenRouter maps the
  model to several Artificial Analysis variants (for example, reasoning and
  non-reasoning modes) and none matches the model, each variant is listed under
  `variants`, keyed by Artificial Analysis slug.
- `design_arena`: Elo, win rate, Elo percentile, placements, and average
  generation time from Design Arena, keyed by Design Arena model, arena, and
  category.
- `vals_ai`: accuracy, standard error, latency, and cost per test from Vals AI,
  keyed by Vals AI model and benchmark.
- `openrouter`: OpenRouter's own benchmark runs, keyed by benchmark and listing
  each provider endpoint's score and run count over the last `lookback_days`.

`null` means the source did not publish that metric for the model. Sources with
no data for a model are omitted.

Sources: [Artificial Analysis](https://artificialanalysis.ai/),
[OpenRouter](https://openrouter.ai/), [Design Arena](https://www.designarena.ai/),
and [Vals AI](https://www.vals.ai/). The generated data is subject to each
source's terms and attribution requirements.
