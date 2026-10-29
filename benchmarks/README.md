# Model benchmarks

This directory mirrors the relative paths of model files in `providers/`: every
provider model file has a benchmark file with the same name and sub-path. Each
file contains:

- `model`: the provider model name;
- `artificial_analysis_id` and `artificial_analysis_slug`: the repository's
  Artificial Analysis match, when one exists; and
- `metrics`, grouped by source. `metrics: {}` means no source publishes
  benchmark data for the model, or the model could not be matched to any
  source.

Data comes from each model's OpenRouter benchmark page
(`https://openrouter.ai/<model>#benchmarks`) and directly from the source
websites: [artificialanalysis.ai](https://artificialanalysis.ai/), Design Arena
model pages on [designarena.ai](https://www.designarena.ai/), and Vals AI
benchmark pages on [vals.ai](https://www.vals.ai/). Models are matched to
OpenRouter and to each source by exact identifiers first, then by name; a name
match is used only above a confidence threshold, and version, size, creator,
and variant (for example, reasoning or preview) must agree.

Within a sub-section, values are merged with this precedence: source website >
Artificial Analysis Free Data API > OpenRouter. When sources disagree, the
source website wins; lower-precedence sources only fill metrics the others
leave missing.

Metric sub-sections:

- `artificial_analysis`: Artificial Analysis evaluations and indexes. Metric
  names drop the `artificial_analysis_` prefix. `gdpval_aa` is the normalized
  GDPval score and `gdpval_aa_elo` the GDPval Elo. Image, video, and speech
  models report arena Elo fields instead. When the model maps to several
  Artificial Analysis variants (for example, reasoning and non-reasoning modes)
  and none matches the model, each variant is listed under `variants`, keyed by
  Artificial Analysis slug.
- `design_arena`: Elo, win rate, Elo percentile, placements, and average
  generation time from Design Arena, keyed by Design Arena model, arena, and
  category. Entries from the Design Arena site may also include `rank`, and
  their placements are per category.
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
