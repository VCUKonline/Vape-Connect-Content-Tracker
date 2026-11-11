from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"
PRODUCTS_CSV = INPUT_DIR / "eligible_products.csv"
VARIANTS_CSV = INPUT_DIR / "eligible_variants.csv"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value)) or not str(value).strip()


def parse_json(value: Any, default: Any = None) -> Any:
    if is_blank(value):
        return default
    try:
        return json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return default


def html_to_text(value: Any) -> str:
    if is_blank(value):
        return ""
    soup = BeautifulSoup(str(value), "html.parser")
    for tag in soup(["style", "script", "noscript", "svg"]):
        tag.decompose()
    # Keep boundaries between headings, paragraphs, list items and table rows.
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "tr", "br"]):
        tag.insert_before("\n")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def flatten_metafields(value: Any) -> tuple[str, dict[str, Any]]:
    """Return searchable metafield text and a key->value map."""
    fields = parse_json(value, [])
    if not isinstance(fields, list):
        return "", {}
    pieces: list[str] = []
    mapped: dict[str, Any] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        namespace = str(field.get("namespace", "")).strip()
        key = str(field.get("key", "")).strip()
        val = field.get("value", "")
        full_key = f"{namespace}.{key}" if namespace else key
        mapped[full_key.casefold()] = val
        if not is_blank(val):
            pieces.extend([key.replace("_", " "), str(val)])
    return html_to_text(" ".join(pieces)), mapped


def decode_list_field(value: Any) -> list[Any]:
    parsed = parse_json(value, None)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("items", "questions", "faqs", "values"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    return []


def metafield_presence(meta: dict[str, Any], tokens: tuple[str, ...]) -> bool:
    for key, value in meta.items():
        if any(token in key for token in tokens) and not is_blank(value):
            # A JSON list of references counts as present if it contains entries.
            parsed = parse_json(value, None)
            if isinstance(parsed, list):
                if len(parsed) > 0:
                    return True
            elif str(value).strip():
                return True
    return False


def detect_sections(description: str, meta_text: str, meta: dict[str, Any]) -> dict[str, str]:
    text = f"{description}\n{meta_text}".casefold()
    checks = {
        "key_features": (r"key features|features|product highlights|why choose|main benefits", ("feature", "highlight")),
        "specifications": (r"specifications|technical details|product details|tech specs|dimensions|battery capacity", ("spec", "technical_detail")),
        "faqs": (r"\bfaqs?\b|frequently asked questions", ("faq",)),
        "how_to_use": (r"how to use|how to install|instructions|getting started|usage instructions|directions", ("how_to", "instruction", "usage")),
    }
    result = {}
    for name, (pattern, meta_tokens) in checks.items():
        found_text = bool(re.search(pattern, text))
        found_meta = metafield_presence(meta, meta_tokens)
        result[name] = "Present" if found_text or found_meta else "Missing"
    return result


def normalize_analysis_text(text: str) -> str:
    """Normalize harmless spacing before punctuation for checks only.

    The original Shopify HTML/description is never changed or written back.
    """
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return text


def possible_text_issues(text: str) -> list[dict[str, str]]:
    """Conservative deterministic checks; these are prompts for human review, not grammar proof."""
    findings: list[dict[str, str]] = []
    if not text:
        return findings
    patterns = [
        (r"\b(the|a|an|and|to|of|is|it)\s+\1\b", "Possible repeated word", "Check for an accidentally repeated word."),
        (r"[!?]{3,}", "Repeated punctuation", "Review excessive repeated punctuation."),
        (r"\b(?:teh|recieve|seperate|definately|occured|untill)\b", "Possible spelling mistake", "Review the highlighted spelling."),
    ]
    for pattern, label, recommendation in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            excerpt = text[max(0, match.start()-45):min(len(text), match.end()+45)].replace("\n", " ")
            findings.append({
                "category": "Possible Grammar/Spelling",
                "severity": "Low",
                "issue": label,
                "evidence": excerpt,
                "recommendation": recommendation,
            })
            if len(findings) >= 30:
                return findings
    return findings


def check_variant_options(product: pd.Series, group: pd.DataFrame, search_text: str) -> list[dict[str, str]]:
    """Literal option check. Absence is informational, not proof of an incorrect listing."""
    rows: list[dict[str, str]] = []
    normalized_description = re.sub(r"[^a-z0-9]+", " ", search_text.casefold())
    normalized_description = f" {normalized_description} "
    seen: set[tuple[str, str]] = set()
    for _, variant in group.iterrows():
        options = parse_json(variant.get("selected_options_json"), [])
        if not isinstance(options, list):
            continue
        for option in options:
            if not isinstance(option, dict):
                continue
            name = str(option.get("name", "")).strip()
            value = str(option.get("value", "")).strip()
            if len(value) < 3:
                continue
            normalized_value = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
            if not normalized_value:
                continue
            key = (name.casefold(), normalized_value)
            if key in seen:
                continue
            seen.add(key)
            if f" {normalized_value} " not in normalized_description:
                rows.append({
                    "product_id": str(product.get("product_id", "")),
                    "product_name": str(product.get("title", "")),
                    "variant_name": str(variant.get("variant_title", "")),
                    "option_name": name,
                    "option_value": value,
                    "finding": "Option value not explicitly mentioned in product description or detected metafield text",
                    "severity": "Info",
                    "note": "Not a confirmed error. The Shopify variant selector may already communicate this option. Check only if the product page should list every option value.",
                })
    return rows


def audit_product(product: pd.Series, group: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    description_original = html_to_text(product.get("description_html", ""))
    description = normalize_analysis_text(description_original)  # analysis-only copy
    meta_text, meta = flatten_metafields(product.get("metafields_json", ""))
    combined_text = f"{description}\n{meta_text}".strip()
    sections = detect_sections(description, meta_text, meta)
    issues: list[dict[str, str]] = []
    pid = str(product.get("product_id", ""))
    title = str(product.get("title", ""))
    brand = str(product.get("brand", ""))

    if len(description) == 0:
        issues.append({"category": "Description", "severity": "High", "issue": "Product description is empty", "evidence": "No readable text was extracted from description_html.", "recommendation": "Add an accurate product description based on verified product information."})
    elif len(description) < 120:
        issues.append({"category": "Description", "severity": "Medium", "issue": "Product description is very short", "evidence": f"Only {len(description)} readable characters were extracted.", "recommendation": "Review whether customers have enough product-specific information to understand the listing."})

    section_labels = {
        "key_features": "Key Features",
        "specifications": "Specifications",
        "faqs": "FAQs",
        "how_to_use": "How to Use",
    }
    for key, label in section_labels.items():
        if sections[key] == "Missing":
            issues.append({"category": label, "severity": "Medium", "issue": f"No clear {label} section detected", "evidence": "Basic heading and metafield checks did not identify this section.", "recommendation": f"Check whether {label.lower()} information is applicable; add it if useful and supported by verified product information."})

    if is_blank(product.get("seo_title", "")):
        issues.append({"category": "SEO", "severity": "Low", "issue": "SEO title is empty", "evidence": "Shopify SEO title field is blank.", "recommendation": "Consider adding a concise, accurate page title."})
    if is_blank(product.get("seo_description", "")):
        issues.append({"category": "SEO", "severity": "Low", "issue": "SEO description is empty", "evidence": "Shopify SEO description field is blank.", "recommendation": "Consider adding a concise, factual meta description."})

    text_issues = possible_text_issues(description)
    issues.extend(text_issues)
    variant_checks = check_variant_options(product, group, combined_text)

    # Transparent heuristic score: section/description/SEO checks only; not an AI quality grade.
    score = 100
    if len(description) == 0:
        score -= 35
    elif len(description) < 120:
        score -= 15
    score -= sum(10 for value in sections.values() if value == "Missing")
    score -= 5 if is_blank(product.get("seo_title", "")) else 0
    score -= 5 if is_blank(product.get("seo_description", "")) else 0
    score = max(0, score)

    summary = {
        "product_id": pid,
        "product_name": title,
        "brand": brand,
        "product_type": str(product.get("product_type", "")),
        "variant_count": len(group),
        "description_characters": len(description),
        "description_score": score,
        "score_type": "rule_based_completeness_indicator_not_ai_quality_score",
        **sections,
        "possible_grammar_issue_count": len(text_issues),
        "content_issue_count": len(issues),
        "variant_option_values_to_review": len(variant_checks),
        "seo_title_present": not is_blank(product.get("seo_title", "")),
        "seo_description_present": not is_blank(product.get("seo_description", "")),
        "product_url": str(product.get("online_store_url", "")),
        "audit_summary": "Rule-based checks only. No AI or external API was used. Findings require human review.",
        "manual_review_required": True,
    }
    issue_rows = [{"product_id": pid, "product_name": title, "brand": brand, **item} for item in issues]
    return summary, issue_rows, variant_checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Vape Connect rule-based product content audit; no AI/API key required")
    parser.add_argument("--limit", type=int, default=10, help="Number of products to audit (default: 10; use 317 for all)")
    parser.add_argument("--all", action="store_true", help="Audit all eligible products")
    args = parser.parse_args()

    if not PRODUCTS_CSV.exists() or not VARIANTS_CSV.exists():
        print("Input CSVs not found. Place eligible_products.csv and eligible_variants.csv in data/input/.")
        return 2

    products = pd.read_csv(PRODUCTS_CSV, dtype=str, keep_default_na=False)
    variants = pd.read_csv(VARIANTS_CSV, dtype=str, keep_default_na=False)
    required_p = {"product_id", "title", "description_html", "metafields_json", "seo_title", "seo_description"}
    required_v = {"product_id", "variant_id", "variant_title", "selected_options_json"}
    if not required_p.issubset(products.columns) or not required_v.issubset(variants.columns):
        print("CSV columns do not match Stage 1 exports. Use the latest Stage 1 CSV files.")
        return 2

    limit = len(products) if args.all else max(1, args.limit)
    pilot = products.head(limit).copy()
    product_results: list[dict[str, Any]] = []
    issue_results: list[dict[str, Any]] = []
    variant_results: list[dict[str, Any]] = []
    started = datetime.now(timezone.utc)

    print(f"Starting rule-based audit: {len(pilot)} products | variants linked from Stage 1 | AI/API: OFF")
    for number, (_, product) in enumerate(pilot.iterrows(), start=1):
        group = variants[variants["product_id"] == product["product_id"]].copy()
        summary, issues, variant_checks = audit_product(product, group)
        product_results.append(summary)
        issue_results.extend(issues)
        variant_results.extend(variant_checks)
        print(f"[{number}/{len(pilot)}] {product['title']} | {len(group)} variants | score {summary['description_score']} | {len(issues)} content findings")

    product_df = pd.DataFrame(product_results)
    issue_columns = ["product_id", "product_name", "brand", "category", "severity", "issue", "evidence", "recommendation"]
    variant_columns = ["product_id", "product_name", "variant_name", "option_name", "option_value", "finding", "severity", "note"]
    issue_df = pd.DataFrame(issue_results, columns=issue_columns)
    variant_df = pd.DataFrame(variant_results, columns=variant_columns)

    product_df.to_csv(OUTPUT_DIR / "stage2_product_audit.csv", index=False, encoding="utf-8-sig")
    issue_df.to_csv(OUTPUT_DIR / "stage2_content_issues.csv", index=False, encoding="utf-8-sig")
    variant_df.to_csv(OUTPUT_DIR / "stage2_variant_checks.csv", index=False, encoding="utf-8-sig")

    summary = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "started_at_utc": started.isoformat(),
        "audit_type": "basic_rule_based_no_ai",
        "products_audited": len(product_df),
        "variants_in_audited_products": int(product_df["variant_count"].sum()) if not product_df.empty else 0,
        "content_findings": len(issue_df),
        "variant_option_values_to_review": len(variant_df),
        "high_severity_findings": int((issue_df["severity"] == "High").sum()) if not issue_df.empty else 0,
        "outputs": ["stage2_product_audit.csv", "stage2_content_issues.csv", "stage2_variant_checks.csv", "stage2_summary.json"],
        "limitations": [
            "No AI, OpenAI API key, internet search or Shopify API calls are used.",
            "Grammar checks are limited deterministic patterns and cannot replace a human proofread.",
            "Section detection uses headings and selected metafield names; non-standard sections may be missed.",
            "Variant option values not mentioned in description are informational review prompts, not confirmed errors.",
            "The score is a transparent completeness indicator, not a measure of factual accuracy or regulatory compliance."
        ]
    }
    (OUTPUT_DIR / "stage2_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nAudit complete. No API key required.")
    print(json.dumps(summary, indent=2))
    print(f"Reports saved to: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
