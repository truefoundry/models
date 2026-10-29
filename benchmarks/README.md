# Artificial Analysis benchmarks

This directory mirrors the relative paths of model files in `providers/`. A file
is present when the corresponding language model can be matched to the
Artificial Analysis catalog. Each generated YAML file contains:

- the provider model name;
- the current Artificial Analysis model ID and slug; and
- every metric returned by the Artificial Analysis Free Data API.

`null` means Artificial Analysis did not publish that metric for the model in
the fetched catalog. Non-language models and language models that Artificial
Analysis does not catalog have no benchmark file.

Source: [Artificial Analysis](https://artificialanalysis.ai/). The generated
data is subject to the Artificial Analysis Data API terms and attribution
requirements.
