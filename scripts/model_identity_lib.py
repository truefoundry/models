"""Shared helpers for canonical model identity and Artificial Analysis IDs."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator
from uuid import UUID

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDERS_DIR = REPO_ROOT / "providers"
EXCEPTIONS_PATH = REPO_ROOT / "canonical_exceptions.yaml"
REPORTS_DIR = REPO_ROOT / "reports"

LANGUAGE_MODES = frozenset({"chat", "completion"})
SKIP_FILENAMES = frozenset({"default.yaml", "provider-config.yaml"})

# Providers that host others' weights — creator must come from the model ID / path.
HOST_PROVIDERS = frozenset(
    {
        "aws-bedrock",
        "aws-bedrock-mantle",
        "azure-ai-foundry",
        "azure-open-ai",
        "cerebras",
        "databricks",
        "deepinfra",
        "groq",
        "google-vertex",
        "microsoft-foundry",
        "openrouter",
        "sambanova",
        "together-ai",
        "truefoundry-managed",
        "typesafe",
        "wafer",
    }
)

# Provider directory -> default creator when the model ID has no creator segment.
PROVIDER_CREATOR = {
    "ai21": "ai21",
    "anthropic": "anthropic",
    "cohere": "cohere",
    "deepgram": "deepgram",
    "elevenlabs": "elevenlabs",
    "google-gemini": "google",
    "mistral-ai": "mistral",
    "openai": "openai",
    "perplexity-ai": "perplexity",
    "xai": "xai",
}

# Normalize org / path / ID creator tokens to a stable creator slug.
CREATOR_ALIASES = {
    "ai21labs": "ai21",
    "ai21-labs": "ai21",
    "alibaba-cloud": "alibaba",
    "aliyun": "alibaba",
    "amazon": "amazon",
    "anthropic": "anthropic",
    "cohere": "cohere",
    "deepseek": "deepseek",
    "deepseek-ai": "deepseek",
    "google": "google",
    "googlegemini": "google",
    "ibm": "ibm",
    "ibm-granite": "ibm",
    "kimi": "kimi",
    "meta": "meta",
    "meta-llama": "meta",
    "microsoft": "microsoft",
    "mistral": "mistral",
    "mistralai": "mistral",
    "moonshot": "kimi",
    "moonshotai": "kimi",
    "nvidia": "nvidia",
    "openai": "openai",
    "perplexity": "perplexity",
    "qwen": "alibaba",
    "spacexai": "xai",
    "x-ai": "xai",
    "xai": "xai",
    "z-ai": "zai",
    "zai": "zai",
    "zai-org": "zai",
}

# Databricks / system.ai prefixes that encode a creator.
DATABRICKS_CREATOR_PREFIXES = (
    ("claude-", "anthropic"),
    ("gpt-", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("gemini-", "google"),
    ("gemma-", "google"),
    ("llama-", "meta"),
    ("meta-llama-", "meta"),
    ("mistral-", "mistral"),
    ("mixtral-", "mistral"),
    ("gpt-oss-", "openai"),
    ("mpt-", "databricks"),
)

BEDROCK_REGION_PREFIXES = (
    "us-gov.",
    "us.",
    "eu.",
    "apac.",
    "ap.",
    "global.",
    "au.",
    "jp.",
    "me.",
    "ca.",
    "af.",
    "il.",
    "sa.",
    "in.",
)

# OpenRouter / aggregator suffixes that are deployment flavours, not foundation identity.
DEPLOYMENT_SUFFIXES = (
    ":free",
    ":beta",
    ":extended",
    ":nitro",
    ":floor",
    ":exacto",
    ":self",
)

DATE_SUFFIX_RE = re.compile(
    r"(?:-|@)(?:"
    r"\d{4}-\d{2}-\d{2}"
    r"|\d{8}"
    r"|\d{4}-\d{2}"
    r")$"
)
BEDROCK_VERSION_RE = re.compile(r"-v\d+(?::\d+)?$")
TRAILING_PIN_RE = re.compile(r"-(?:0\d{2}|\d{3})$")
CANONICAL_RE = re.compile(r"^[a-z0-9][a-z0-9._+-]*/[a-z0-9][a-z0-9._+:-]*$")
AA_API_URL = "https://artificialanalysis.ai/api/v2/language/models/free"


@dataclass
class ModelEntry:
    path: Path
    provider: str
    model: str
    mode: str
    data: dict[str, Any]
    canonical_model: str | None = None
    external_ids: dict[str, str] | None = None

    @property
    def rel_path(self) -> str:
        return str(self.path.relative_to(REPO_ROOT)).replace("\\", "/")


@dataclass
class Proposal:
    path: str
    provider_id: str
    creator: str
    proposed_canonical: str
    rule: str
    group_paths: list[str] = field(default_factory=list)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(
        data,
        sort_keys=True,
        default_flow_style=False,
        allow_unicode=True,
        width=256,
    )


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = dump_yaml(data)
    path.write_text(text, encoding="utf-8")


def iter_model_files(providers_dir: Path = PROVIDERS_DIR) -> Iterator[Path]:
    for path in sorted(providers_dir.rglob("*.yaml")):
        if path.name in SKIP_FILENAMES:
            continue
        yield path


def load_model_entry(path: Path, providers_dir: Path | None = None) -> ModelEntry | None:
    providers_dir = providers_dir or PROVIDERS_DIR
    data = load_yaml(path)
    if not isinstance(data, dict):
        return None
    model = data.get("model")
    mode = data.get("mode")
    if not isinstance(model, str) or not isinstance(mode, str):
        return None
    rel = path.relative_to(providers_dir)
    provider = rel.parts[0]
    canonical = data.get("canonical_model")
    external = data.get("external_ids")
    return ModelEntry(
        path=path,
        provider=provider,
        model=model,
        mode=mode,
        data=data,
        canonical_model=canonical if isinstance(canonical, str) else None,
        external_ids=external if isinstance(external, dict) else None,
    )


def load_language_models(providers_dir: Path = PROVIDERS_DIR) -> list[ModelEntry]:
    entries: list[ModelEntry] = []
    for path in iter_model_files(providers_dir):
        entry = load_model_entry(path, providers_dir)
        if entry and entry.mode in LANGUAGE_MODES:
            entries.append(entry)
    return entries


def load_aliases(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = load_yaml(path) or {}
    if isinstance(data, dict) and "aliases" in data:
        aliases = data["aliases"] or {}
    else:
        aliases = data
    if not isinstance(aliases, dict):
        raise ValueError(f"Invalid aliases file: {path}")
    return {str(k): str(v) for k, v in aliases.items()}


def load_external_id_map(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    data = load_yaml(path) or {}
    if isinstance(data, dict) and "external_ids" in data:
        mapping = data["external_ids"] or {}
    else:
        mapping = data
    if not isinstance(mapping, dict):
        raise ValueError(f"Invalid external ids file: {path}")
    out: dict[str, dict[str, str]] = {}
    for canonical, ids in mapping.items():
        if ids is None:
            continue
        if not isinstance(ids, dict):
            raise ValueError(f"Invalid external id entry for {canonical}")
        cleaned = {
            k: str(v)
            for k, v in ids.items()
            if v is not None and str(v).strip() != ""
        }
        if cleaned:
            out[str(canonical)] = cleaned
    return out


def load_exceptions(path: Path = EXCEPTIONS_PATH) -> dict[str, str]:
    if not path.exists():
        return {}
    data = load_yaml(path) or []
    if isinstance(data, dict) and "exceptions" in data:
        rows = data["exceptions"] or []
    else:
        rows = data
    if not isinstance(rows, list):
        raise ValueError(f"Invalid exceptions file: {path}")
    out: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_path = row.get("path")
        reason = row.get("reason")
        if isinstance(model_path, str) and isinstance(reason, str):
            out[model_path.replace("\\", "/")] = reason
    return out


def normalize_creator(raw: str) -> str:
    token = raw.strip().lower().lstrip("~")
    token = token.replace("_", "-")
    return CREATOR_ALIASES.get(token, token)


def _strip_deployment_suffixes(name: str) -> tuple[str, list[str]]:
    rules: list[str] = []
    changed = True
    while changed:
        changed = False
        lower = name.lower()
        for suffix in DEPLOYMENT_SUFFIXES:
            if lower.endswith(suffix):
                name = name[: -len(suffix)]
                rules.append(f"strip_deployment:{suffix}")
                changed = True
                break
    return name, rules


def normalize_foundation_name(name: str) -> tuple[str, list[str]]:
    """Normalize a foundation-model segment. Does not invent creator."""
    rules: list[str] = []
    original = name
    name = name.strip().lower().lstrip("~")
    name = name.replace(" ", "-")

    name, dep_rules = _strip_deployment_suffixes(name)
    rules.extend(dep_rules)

    # Preserve explicit reasoning markers; normalize separator.
    if ":thinking" in name:
        name = name.replace(":thinking", "-thinking")
        rules.append("normalize_thinking_marker")
    if name.endswith(":reasoning"):
        name = name[: -len(":reasoning")] + "-reasoning"
        rules.append("normalize_reasoning_marker")

    # Vertex pins: foo@20241022, foo@001, foo@latest
    if "@" in name:
        base, _, rest = name.partition("@")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}|\d{4}-\d{2}|\d{3}|latest|default", rest):
            name = base
            rules.append("strip_at_pin")

    # Bedrock style version suffix.
    if BEDROCK_VERSION_RE.search(name):
        name = BEDROCK_VERSION_RE.sub("", name)
        rules.append("strip_bedrock_version")
    if name.endswith(":0") or re.search(r":\d+$", name):
        name = re.sub(r":\d+$", "", name)
        rules.append("strip_numeric_colon_suffix")

    # Release-date suffixes on an otherwise stable foundation id.
    while DATE_SUFFIX_RE.search(name):
        name = DATE_SUFFIX_RE.sub("", name)
        rules.append("strip_date_suffix")

    # Gemini-style three-digit pins (gemini-2.0-flash-001).
    if TRAILING_PIN_RE.search(name) and any(
        tok in name for tok in ("gemini-", "imagen-", "palm-", "chat-bison", "text-bison", "code-bison")
    ):
        name = TRAILING_PIN_RE.sub("", name)
        rules.append("strip_google_pin")

    # Moving alias suffix.
    if name.endswith("-latest"):
        name = name[: -len("-latest")]
        rules.append("strip_latest")

    # Dots in version numbers -> hyphens (gpt-4.1-mini -> gpt-4-1-mini).
    if "." in name:
        name = name.replace(".", "-")
        rules.append("dot_to_hyphen")

    # Collapse accidental duplicate hyphens.
    collapsed = re.sub(r"-{2,}", "-", name).strip("-")
    if collapsed != name:
        rules.append("collapse_hyphens")
        name = collapsed

    if name != original.lower() and not rules:
        rules.append("lowercase")
    elif not rules:
        rules.append("identity")
    return name, rules


# First-segment org tokens used by Bedrock-style IDs (creator.model).
# Intentionally excludes version-like segments such as "gpt-4".
BEDROCK_CREATOR_TOKENS = frozenset(
    {
        "ai21",
        "amazon",
        "anthropic",
        "cohere",
        "deepseek",
        "google",
        "meta",
        "mistral",
        "moonshot",
        "moonshotai",
        "nvidia",
        "openai",
        "qwen",
        "stability",
        "writer",
        "twelvelabs",
        "luma",
        "minimax",
        "xai",
        "zai",
    }
)


def split_provider_model_id(model_id: str) -> tuple[str | None, str]:
    """Return (creator_hint, remainder) from a provider API model id."""
    lower = model_id.strip().lower().lstrip("~")

    # org/model (OpenRouter, Together, DeepInfra, Vertex partners)
    if "/" in lower:
        creator, _, rest = lower.partition("/")
        return normalize_creator(creator), rest

    # Databricks system.ai.* / databricks-*
    if lower.startswith("system.ai."):
        rest = lower[len("system.ai.") :]
        return _databricks_creator(rest), rest
    if lower.startswith("databricks-"):
        rest = lower[len("databricks-") :]
        return _databricks_creator(rest), rest

    # Bedrock / mantle: [region.]creator.model — only when creator token is known.
    working = lower
    for prefix in BEDROCK_REGION_PREFIXES:
        if working.startswith(prefix):
            working = working[len(prefix) :]
            break
    if "." in working:
        creator, _, rest = working.partition(".")
        if creator in BEDROCK_CREATOR_TOKENS and rest:
            return normalize_creator(creator), rest

    return None, lower


def _databricks_creator(rest: str) -> str | None:
    for prefix, creator in DATABRICKS_CREATOR_PREFIXES:
        if rest.startswith(prefix):
            return creator
    return None


def _path_creator_subdir(provider: str, path: Path | None) -> str | None:
    """Return creator subdirectory under providers/<provider>/<creator>/file.yaml."""
    if path is None:
        return None
    try:
        rel = path.resolve().relative_to(PROVIDERS_DIR.resolve())
    except Exception:
        parts = Path(str(path)).parts
        if "providers" in parts:
            idx = parts.index("providers")
            rel_parts = parts[idx + 1 :]
        else:
            rel_parts = parts
        rel = Path(*rel_parts) if rel_parts else Path()
    parts = rel.parts
    # <provider>/<creator>/model.yaml  (len >= 3)
    if len(parts) >= 3 and parts[0] == provider:
        sub = parts[1]
        if sub and not sub.endswith(".yaml"):
            return normalize_creator(sub)
    return None


def infer_creator(provider: str, model_id: str, path: Path | None = None) -> tuple[str | None, str]:
    """Infer (creator, rule)."""
    if "/" in model_id:
        seg_creator, foundation_source, seg_rule = _foundation_from_multi_segment(model_id)
        if seg_creator and seg_creator not in _HOST_ORG_CREATORS:
            # Prefer nested/real org; still allow well-known prefix on foundation to win later.
            prefix = _creator_from_well_known_prefix(foundation_source.lower())
            if prefix:
                return prefix, "creator_from_well_known_prefix"
            return seg_creator, seg_rule
        prefix = _creator_from_well_known_prefix(foundation_source.lower())
        if prefix:
            return prefix, "creator_from_well_known_prefix"

    hint, _ = split_provider_model_id(model_id)
    if hint and hint not in _HOST_ORG_CREATORS:
        return hint, "creator_from_model_id"

    path_creator = _path_creator_subdir(provider, path)
    if path_creator:
        return path_creator, "creator_from_path"

    mid = model_id.lower().lstrip("~")
    prefix_creator = _creator_from_well_known_prefix(mid)
    if prefix_creator:
        return prefix_creator, "creator_from_well_known_prefix"

    if provider == "databricks":
        rest = mid.removeprefix("databricks-").removeprefix("system.ai.")
        creator = _databricks_creator(rest)
        return creator, "creator_databricks"

    if provider in PROVIDER_CREATOR:
        return PROVIDER_CREATOR[provider], "creator_from_provider"

    return None, "creator_unknown"


def _creator_from_well_known_prefix(mid: str) -> str | None:
    rules = (
        ("claude", "anthropic"),
        ("chatgpt-", "openai"),
        ("gpt-", "openai"),
        ("o1", "openai"),
        ("o3", "openai"),
        ("o4", "openai"),
        ("codex-", "openai"),
        ("davinci", "openai"),
        ("curie", "openai"),
        ("babbage", "openai"),
        ("ada", "openai"),
        ("computer-use-", "openai"),
        ("text-ada", "openai"),
        ("text-babbage", "openai"),
        ("text-curie", "openai"),
        ("text-davinci", "openai"),
        ("code-cushman", "openai"),
        ("code-davinci", "openai"),
        ("gemini-", "google"),
        ("gemma", "google"),
        ("medlm-", "google"),
        ("text-unicorn", "google"),
        ("code-gecko", "google"),
        ("codechat-bison", "google"),
        ("chat-bison", "google"),
        ("text-bison", "google"),
        ("code-bison", "google"),
        ("llama", "meta"),
        ("codellama", "meta"),
        ("mistral-", "mistral"),
        ("mixtral-", "mistral"),
        ("ministral", "mistral"),
        ("magistral", "mistral"),
        ("devstral", "mistral"),
        ("codestral", "mistral"),
        ("pixtral", "mistral"),
        ("cohere-command", "cohere"),
        ("cohere-", "cohere"),
        ("command", "cohere"),
        ("deepseek", "deepseek"),
        ("qwen", "alibaba"),
        ("qwq-", "alibaba"),
        ("qwerky", "alibaba"),
        ("grok", "xai"),
        ("phi-", "microsoft"),
        ("phi", "microsoft"),
        ("jamba", "ai21"),
        ("j2-", "ai21"),
        ("ai21-", "ai21"),
        ("kimi", "kimi"),
        ("moonshot", "kimi"),
        ("zai-glm", "zai"),
        ("zai-", "zai"),
        ("glm-", "zai"),
        ("glm", "zai"),
        ("aion-", "aion-labs"),
        ("aion-rp-", "aion-labs"),
        ("shisa-", "shisa-ai"),
        ("ui-tars", "bytedance"),
        ("nemotron", "nvidia"),
        ("nova-", "amazon"),
        ("minimax", "minimax"),
        ("sonar", "perplexity"),
        ("r1-1776", "perplexity"),
        ("ernie-", "baidu"),
        ("hunyuan-", "tencent"),
        ("reka-", "reka"),
        ("lfm-", "liquid"),
        ("mimo-", "xiaomi"),
        ("mai-", "microsoft"),
        ("allam-", "saudi-allam"),
        ("jais-", "core42"),
        ("mpt-", "databricks"),
        ("dolphin", "cognitivecomputations"),
        ("hermes-", "nousresearch"),
        ("nous-hermes", "nousresearch"),
        ("wizardlm", "microsoft"),
        ("internvl", "opengvlab"),
        ("sarvam-", "sarvam"),
        ("inflection-", "inflection"),
        ("mythomax", "gryphe"),
        ("mythalion", "gryphe"),
        ("noromaid", "neversleep"),
        ("toppy-", "undi95"),
        ("goliath-", "alpindale"),
        ("llemma", "eleutherai"),
        ("mercury", "inception"),
        ("morph-", "morph"),
        ("anubis-", "thedrummer"),
        ("skyfall-", "thedrummer"),
        ("rocinante-", "thedrummer"),
        ("unslopnemo", "thedrummer"),
        ("magnum-", "anthracite-org"),
        ("euryale", "sao10k"),
        ("lunaris", "sao10k"),
        ("fimbulvetr", "sao10k"),
        ("midnight-rose", "sophosympatheia"),
        ("remm-slerp", "undi95"),
        ("sorcererlm", "raifle"),
        ("weaver", "openpipe"),
        ("virtuoso-", "arcee-ai"),
        ("coder-large", "arcee-ai"),
        ("spotlight", "arcee-ai"),
        ("maestro-", "arcee-ai"),
        ("valkyrie-", "arcee-ai"),
        ("horizon-", "openrouter"),
        ("muse-", "meta"),
        ("inkling-", "microsoft"),
    )
    for prefix, creator in rules:
        if mid.startswith(prefix):
            return creator
    # Secondary patterns where the family token is not at the start.
    secondary = (
        ("euryale", "sao10k"),
        ("lunaris", "sao10k"),
        ("hermes", "nousresearch"),
        ("celeste", "aetherwiing"),
        ("inferor", "aetherwiing"),
    )
    for token, creator in secondary:
        if token in mid:
            return creator
    return None


_HOST_ORG_CREATORS = frozenset(
    {
        "togethercomputer",
        "together",
        "databricks",
        "nim",
        "openrouter",
        "huggingface",
        "hf-inference",
        "microsoft-foundry",
        "azure",
        "aws",
        "bedrock",
    }
)


def _reassign_creator_from_foundation(creator: str | None, foundation: str) -> tuple[str | None, str | None]:
    """If a host org published upstream weights, prefer the upstream creator."""
    if creator and creator not in _HOST_ORG_CREATORS and creator not in HOST_PROVIDERS:
        return creator, None
    for prefix, upstream in (
        ("meta-llama-", "meta"),
        ("llama-", "meta"),
        ("claude-", "anthropic"),
        ("gpt-", "openai"),
        ("gemini-", "google"),
        ("gemma-", "google"),
        ("qwen", "alibaba"),
        ("deepseek", "deepseek"),
        ("mistral-", "mistral"),
        ("mixtral-", "mistral"),
        ("grok-", "xai"),
    ):
        if foundation.startswith(prefix):
            return upstream, f"creator_from_foundation:{upstream}"
    return creator, None


def _foundation_from_multi_segment(model_id: str) -> tuple[str | None, str, str]:
    """
    Handle org/model and host/org/model IDs.
    Returns (creator_or_none, foundation_source, rule).
    """
    mid = model_id.strip().lstrip("~")
    parts = [p for p in mid.split("/") if p]
    if len(parts) < 2:
        return None, mid, "single_segment"

    # Drop known hosting prefixes (nim, azure_ai, ...).
    host_prefixes = {"nim", "azure_ai", "azure-ai", "models", "publishers"}
    while len(parts) >= 3 and normalize_creator(parts[0]) in host_prefixes | _HOST_ORG_CREATORS:
        parts = parts[1:]

    if len(parts) >= 2:
        # azure_ai/global/grok-3 → treat last segment as foundation, infer creator from it.
        if parts[0] in {"global", "eu", "us"} and len(parts) == 2:
            return None, parts[-1], "region_prefixed_model"
        creator = normalize_creator(parts[0])
        foundation = "/".join(parts[1:])
        # If foundation still contains a slash (meta/llama-.. under nim), unwrap once more.
        if "/" in foundation:
            nested_creator, nested_rest = foundation.split("/", 1)
            nested_creator = normalize_creator(nested_creator)
            if nested_creator and nested_creator not in _HOST_ORG_CREATORS:
                return nested_creator, nested_rest, "nested_org_model"
        return creator, foundation, "org_model"
    return None, parts[-1], "fallback_leaf"


def propose_canonical(provider: str, model_id: str, path: Path | None = None) -> Proposal:
    creator, creator_rule = infer_creator(provider, model_id, path)
    _, remainder = split_provider_model_id(model_id)
    mid_lower = model_id.lower().lstrip("~")

    if "/" in mid_lower:
        seg_creator, foundation_source, seg_rule = _foundation_from_multi_segment(model_id)
        if seg_creator:
            creator = seg_creator
            creator_rule = seg_rule
        elif creator_rule.startswith("creator_from_model_id"):
            # First-segment host org was not a real creator; keep path/prefix inference.
            pass
    elif mid_lower.startswith("system.ai."):
        foundation_source = mid_lower[len("system.ai.") :]
    elif mid_lower.startswith("databricks-"):
        foundation_source = mid_lower[len("databricks-") :]
    elif split_provider_model_id(model_id)[0] and remainder != mid_lower:
        foundation_source = remainder
    else:
        foundation_source = model_id

    # Foundation must be a single path segment.
    if "/" in foundation_source:
        foundation_source = foundation_source.rsplit("/", 1)[-1]

    foundation, name_rules = normalize_foundation_name(foundation_source)

    # Strip redundant org prefix left in the foundation segment.
    if foundation.startswith("meta-llama-"):
        foundation = "llama-" + foundation[len("meta-llama-") :]
        name_rules.append("strip_meta_llama_org_prefix")
    if foundation.startswith("zai-glm-"):
        foundation = "glm-" + foundation[len("zai-glm-") :]
        name_rules.append("strip_zai_glm_org_prefix")
    if foundation.startswith("zai-"):
        foundation = foundation[len("zai-") :]
        name_rules.append("strip_zai_org_prefix")

    reassigned, reassign_rule = _reassign_creator_from_foundation(creator, foundation)
    if reassign_rule:
        creator = reassigned
        creator_rule = reassign_rule

    if not creator:
        proposed = ""
        rule = creator_rule
    else:
        proposed = f"{creator}/{foundation}"
        rule = "+".join([creator_rule, *name_rules])

    rel = ""
    if path is not None:
        try:
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        except ValueError:
            rel = str(path).replace("\\", "/")

    return Proposal(
        path=rel,
        provider_id=model_id,
        creator=creator or "",
        proposed_canonical=proposed,
        rule=rule,
    )


def is_valid_canonical(value: str) -> bool:
    return bool(CANONICAL_RE.match(value))


def is_valid_uuid(value: str) -> bool:
    try:
        UUID(str(value))
        return True
    except Exception:
        return False


def _ruamel_yaml():
    from ruamel.yaml import YAML

    y = YAML()
    y.preserve_quotes = True
    y.width = 256
    y.indent(mapping=4, sequence=4, offset=2)
    y.default_flow_style = False
    return y


def update_model_yaml_fields(
    path: Path,
    *,
    canonical_model: str | None = None,
    external_ids: dict[str, str] | None = None,
    clear_external_ids: bool = False,
) -> bool:
    """Update identity fields in a model YAML. Returns True if the file changed."""
    original = path.read_text(encoding="utf-8")
    yml = _ruamel_yaml()
    data = yml.load(original)
    if not isinstance(data, dict):
        return False

    changed = False
    if canonical_model is not None and data.get("canonical_model") != canonical_model:
        data["canonical_model"] = canonical_model
        changed = True

    if clear_external_ids and "external_ids" in data:
        del data["external_ids"]
        changed = True
    elif external_ids is not None:
        cleaned = {
            k: v
            for k, v in external_ids.items()
            if v is not None and str(v).strip() != ""
        }
        if not cleaned:
            if "external_ids" in data:
                del data["external_ids"]
                changed = True
        else:
            current = data.get("external_ids")
            current_dict = dict(current) if current is not None else None
            if current_dict != cleaned:
                from ruamel.yaml.comments import CommentedMap

                mapping = CommentedMap()
                for key in sorted(cleaned):
                    mapping[key] = cleaned[key]
                data["external_ids"] = mapping
                changed = True

    if not changed:
        return False

    # Keep top-level keys alphabetically sorted like repo lint.
    from ruamel.yaml.comments import CommentedMap

    ordered = CommentedMap()
    for key in sorted(data.keys(), key=str):
        ordered[key] = data[key]

    from io import StringIO

    buf = StringIO()
    yml.dump(ordered, buf)
    new_text = buf.getvalue()
    if not new_text.endswith("\n"):
        new_text += "\n"
    if new_text == original:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def fetch_aa_language_models(
    api_key: str | None = None,
    *,
    opener: Any = None,
) -> list[dict[str, Any]]:
    key = api_key or os.environ.get("AA_API_KEY")
    if not key:
        raise RuntimeError("AA_API_KEY is required to fetch Artificial Analysis models")

    models: list[dict[str, Any]] = []
    page = 1
    while True:
        url = f"{AA_API_URL}?page={page}"
        req = urllib.request.Request(url, headers={"x-api-key": key})
        try:
            if opener is not None:
                resp = opener.open(req)
            else:
                resp = urllib.request.urlopen(req)
            with resp:
                payload = json.load(resp)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Artificial Analysis API HTTP {exc.code} for page {page}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Artificial Analysis API request failed: {exc}") from exc

        data = payload.get("data")
        if not isinstance(data, list):
            raise RuntimeError("Artificial Analysis API returned unexpected payload (missing data[])")
        models.extend(data)
        pagination = payload.get("pagination") or {}
        if not pagination.get("has_more"):
            break
        page += 1
        if page > 1000:
            raise RuntimeError("Artificial Analysis pagination exceeded safety limit")
    return models


def normalize_aa_text(value: str) -> str:
    text = value.strip().lower()
    text = text.replace("'", "").replace('"', "")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def aa_creator_slug(name: str) -> str:
    return normalize_creator(normalize_aa_text(name).replace("-", ""))


# Map AA creator display names onto our creator slugs.
AA_CREATOR_TO_SLUG = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google": "google",
    "meta": "meta",
    "mistral": "mistral",
    "deepseek": "deepseek",
    "alibaba": "alibaba",
    "amazon": "amazon",
    "nvidia": "nvidia",
    "cohere": "cohere",
    "ai21labs": "ai21",
    "microsoft": "microsoft",
    "perplexity": "perplexity",
    "xiaomi": "xiaomi",
    "kimi": "kimi",
    "zai": "zai",
    "ibm": "ibm",
    "inclusionai": "inclusionai",
    "spacexai": "xai",
    "liquidai": "liquid",
    "minimax": "minimax",
    "bytedanceseed": "bytedance-seed",
    "alleninstituteforai": "allenai",
    "nousresearch": "nousresearch",
    "tencent": "tencent",
    "baidu": "baidu",
}


def match_aa_for_canonical(
    canonical_model: str,
    aa_models: Iterable[dict[str, Any]],
    reviewed: dict[str, dict[str, str]] | None = None,
) -> tuple[str, dict[str, str] | None, list[dict[str, Any]]]:
    """
    Returns (status, match_or_none, candidates).
    status: reviewed | matched | ambiguous | unmatched
    """
    reviewed = reviewed or {}
    if canonical_model in reviewed:
        return "reviewed", reviewed[canonical_model], []

    if "/" not in canonical_model:
        return "unmatched", None, []
    creator, foundation = canonical_model.split("/", 1)
    foundation_norm = normalize_aa_text(foundation)

    same_creator: list[dict[str, Any]] = []
    for row in aa_models:
        mc = (row.get("model_creator") or {}).get("name") or ""
        aa_creator = AA_CREATOR_TO_SLUG.get(normalize_aa_text(mc).replace("-", ""), normalize_creator(mc))
        if aa_creator != creator:
            continue
        same_creator.append(row)

    def _hit(row: dict[str, Any], value: str) -> bool:
        return normalize_aa_text(value) == foundation_norm

    slug_hits = [row for row in same_creator if _hit(row, str(row.get("slug") or ""))]
    if len(slug_hits) == 1:
        row = slug_hits[0]
        return (
            "matched",
            {
                "artificial_analysis_slug": str(row["slug"]),
                "artificial_analysis_id": str(row["id"]),
            },
            slug_hits,
        )
    if len(slug_hits) > 1:
        return "ambiguous", None, slug_hits

    # Exact normalized name only — do not strip reasoning/effort qualifiers.
    name_hits = [row for row in same_creator if _hit(row, str(row.get("name") or ""))]
    if len(name_hits) == 1:
        row = name_hits[0]
        return (
            "matched",
            {
                "artificial_analysis_slug": str(row["slug"]),
                "artificial_analysis_id": str(row["id"]),
            },
            name_hits,
        )
    if len(name_hits) > 1:
        return "ambiguous", None, name_hits
    return "unmatched", None, []
