"""
Check which models under models/providers are missing context_window in their limits.
Deprecated models (isDeprecated: true) are excluded.
Output: temp/context_window_report.txt — grouped by provider.
"""

import os
import yaml

PROVIDERS_DIR = os.path.join(os.path.dirname(__file__), "..", "providers")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "context_window_report.txt")

# Files that are provider-level defaults, not individual models
SKIP_FILES = {"default.yaml"}

# Providers to exclude entirely from the report
EXCLUDE_PROVIDERS: set[str] = {
    "azure-open-ai",
    "azure-ai-foundry",
    "databricks",
}


def check_provider(provider_path: str) -> tuple[int, int, list[str], int]:
    """Return (total_models, models_with_context_window, models_without_context_window, skipped_deprecated)."""
    total = 0
    with_cw = 0
    missing: list[str] = []
    deprecated_count = 0

    for filename in sorted(os.listdir(provider_path)):
        if not filename.endswith(".yaml") or filename in SKIP_FILES:
            continue

        model_name = filename.removesuffix(".yaml")
        filepath = os.path.join(provider_path, filename)

        with open(filepath) as f:
            data = yaml.safe_load(f)

        if data and data.get("isDeprecated") is True:
            deprecated_count += 1
            continue

        total += 1

        limits = data.get("limits") if data else None
        has_context_window = (
            isinstance(limits, dict) and limits.get("context_window") is not None
        )

        if has_context_window:
            with_cw += 1
        else:
            missing.append(model_name)

    return total, with_cw, missing, deprecated_count


def main() -> None:
    providers = sorted(os.listdir(PROVIDERS_DIR))

    grand_total = 0
    grand_with_cw = 0
    grand_deprecated = 0

    excluded_note = f"  |  excluded providers: {', '.join(sorted(EXCLUDE_PROVIDERS))}" if EXCLUDE_PROVIDERS else ""
    lines: list[str] = [
        f"Context Window Coverage Report (deprecated models excluded{excluded_note})",
        "=" * 60,
        "",
    ]

    for provider in providers:
        if provider in EXCLUDE_PROVIDERS:
            continue

        provider_path = os.path.join(PROVIDERS_DIR, provider)
        if not os.path.isdir(provider_path):
            continue

        total, with_cw, missing, deprecated_count = check_provider(provider_path)
        grand_total += total
        grand_with_cw += with_cw
        grand_deprecated += deprecated_count

        deprecated_note = f", {deprecated_count} deprecated skipped" if deprecated_count else ""
        coverage = f"{with_cw}/{total}"
        lines.append(f"Provider: {provider}  ({coverage} have context_window{deprecated_note})")

        if missing:
            lines.append("  Missing context_window:")
            for model in missing:
                lines.append(f"    - {model}")
        else:
            lines.append("  All models have context_window.")

        lines.append("")

    lines += [
        "=" * 60,
        f"Deprecated models skipped:  {grand_deprecated}",
        f"Total models (active):      {grand_total}",
        f"Models with context_window: {grand_with_cw}",
        f"Models without:             {grand_total - grand_with_cw}",
    ]

    report = "\n".join(lines)
    print(report)

    with open(OUTPUT_FILE, "w") as f:
        f.write(report + "\n")

    print(f"\nReport saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
