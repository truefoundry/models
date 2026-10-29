# Model benchmarks

This directory mirrors the relative paths of model files in `providers/`. A
benchmark file exists only when at least one source publishes metrics for that
model. Each file contains:

- `model`: the provider model name;
- `artificial_analysis_id` and `artificial_analysis_slug`: the repository's
  Artificial Analysis match, when one exists; and
- `metrics`, grouped by source. Provider models with no published benchmarks,
  or that could not be matched to any source, have no file here.

Data comes from each model's OpenRouter benchmark page
(`https://openrouter.ai/<model>#benchmarks`) and directly from the source
websites: [artificialanalysis.ai](https://artificialanalysis.ai/), Design Arena
model pages on [designarena.ai](https://www.designarena.ai/), and Vals AI
benchmark pages on [vals.ai](https://www.vals.ai/). LMArena data comes from the
[LMArena leaderboard dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset)
on Hugging Face (`latest` split of every arena). Models are matched to
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
- `lmarena`: LMArena leaderboard positions, keyed by LMArena model name, arena,
  and category. Arenas are the dataset configs (for example, `text`,
  `text_style_control`, `webdev`, `vision`, `search`, `document`, `agent`,
  `text_to_image`, `image_edit`, and `text_to_video`); categories are the
  leaderboard categories within an arena (for example, `overall`, `coding`,
  `math`, `hard_prompts`, or `webdev-react`). Each entry has `rank`, `rating`
  (rounded to two decimals), the `rating_lower` and `rating_upper` confidence
  bounds, `vote_count`, and the leaderboard's `publish_date`. LMArena names are
  display names; qualifiers in parentheses are read as variants (thinking modes,
  reasoning effort such as `(High)` or `(Max)`, Codex harness) or snapshot dates.
  A model may list several LMArena entries when they differ only by such a
  variant, or by a search-enabled configuration (`-search`, `-grounding`).
  Different dated snapshots are never merged, and unversioned `-latest` aliases
  are not matched.
- `openrouter`: OpenRouter's own benchmark runs, keyed by benchmark and listing
  each provider endpoint's score and run count over the last `lookback_days`.

`null` means the source did not publish that metric for the model. Sources with
no data for a model are omitted.

Sources: [Artificial Analysis](https://artificialanalysis.ai/),
[OpenRouter](https://openrouter.ai/), [Design Arena](https://www.designarena.ai/),
[Vals AI](https://www.vals.ai/), and [LMArena](https://lmarena.ai/). The
generated data is subject to each source's terms and attribution requirements.
