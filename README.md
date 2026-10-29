# model-benchmarks

Benchmark metrics for unique models, one file per model:

```
benchmark/<creator>/<model>.yaml   # e.g. benchmark/creator/openai/o3.yaml
```

The layout is `benchmark/creator/<creator>/<name>.yaml`. The `model` field is the
model's `canonical_model` from [truefoundry/models](https://github.com/truefoundry/models),
so `canonical_model: openai/o3` is stored at `benchmark/creator/openai/o3.yaml`.

Each file contains:

- `model`: the `canonical_model`;
- identifiers of the model in each source it has data from
  (`artificial_analysis_id`/`artificial_analysis_slug`, `design_arena_id`,
  `lmarena_id`, `openrouter_id`/`openrouter_permaslug`, `vals_ai_id`); a field is
  a list when several of the source's models map to this one;
- `metrics`, grouped by source: `artificial_analysis`, `design_arena`,
  `lmarena`, `openrouter`, and `vals_ai`.

Models served by several providers appear once. Batch-mode variants (`:batch`)
are folded into their base model. Models with no `canonical_model` (image,
video, speech, and other non-language modes) are not included.

Sources: [Artificial Analysis](https://artificialanalysis.ai/),
[OpenRouter](https://openrouter.ai/), [Design Arena](https://www.designarena.ai/),
[Vals AI](https://www.vals.ai/), and [LMArena](https://lmarena.ai/). The data is
subject to each source's terms and attribution requirements.
