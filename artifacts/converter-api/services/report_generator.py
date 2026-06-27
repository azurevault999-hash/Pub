"""Report and log generation service."""
from __future__ import annotations

import html as html_module
from datetime import datetime, timezone

from models.schemas import ValidationResult, ConversionResult


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ─────────────────────────────────────────────────────────────────────────────
# Plain-text migration report
# ─────────────────────────────────────────────────────────────────────────────

def generate_migration_report(
    filename: str,
    result: ConversionResult,
    output_path: str,
) -> None:
    warnings_lines = [l for l in result.log_lines if "[WARNING]" in l]
    error_lines = [l for l in result.log_lines if "[ERROR]" in l]

    lines = [
        "=" * 70,
        "  SHOPIFY → WOOCOMMERCE MIGRATION REPORT",
        "=" * 70,
        "",
        f"  Generated :  {_now()}",
        f"  Source    :  {filename}",
        "",
        "─" * 70,
        "  PRODUCTS",
        "─" * 70,
        f"  Converted successfully  :  {result.products_converted}",
        f"  Failed / skipped        :  {result.products_failed}",
        "",
        "─" * 70,
        "  PRODUCT TYPE BREAKDOWN",
        "─" * 70,
        f"  Simple products         :  {result.simple_products}",
        f"  Variable products       :  {result.variable_products}",
        "",
        "─" * 70,
        "  VARIANTS",
        "─" * 70,
        f"  Variants converted      :  {result.variants_converted}",
        "",
        "─" * 70,
        "  IMAGES",
        "─" * 70,
        f"  Image references mapped :  {result.images_mapped}",
        "",
        "─" * 70,
        "  CATEGORIES & TAGS",
        "─" * 70,
        f"  Categories mapped       :  {result.categories_mapped}",
        f"  Tags preserved          :  {result.tags_preserved}",
        "",
        "─" * 70,
        "  EXECUTION STATISTICS",
        "─" * 70,
        f"  Warnings                :  {result.warnings}",
        f"  Errors                  :  {result.errors}",
        f"  Execution time          :  {result.execution_time_seconds:.3f}s",
        "",
        "─" * 70,
        "  OUTPUT FILES",
        "─" * 70,
    ]
    for f in result.output_files:
        lines.append(f"  •  {f}")

    # ── Post-export verification results ──────────────────────────────────
    lines += [
        "",
        "─" * 70,
        "  WOO COMMERCE CSV VERIFICATION",
        "─" * 70,
    ]
    if not result.verification_errors:
        lines.append(
            "  ✓  Verification passed — CSV is valid for WooCommerce 10.9.1 native importer."
        )
        lines.append(
            "     • All variation attributes are assigned concrete values (no 'Any')."
        )
        lines.append(
            "     • All parent attributes are marked 'used for variations = 1'."
        )
        lines.append(
            "     • All parent/variation relationships are intact."
        )
    else:
        lines.append(
            f"  ✗  Verification found {len(result.verification_errors)} issue(s):"
        )
        for ve in result.verification_errors:
            lines.append(f"     • {ve}")

    if warnings_lines:
        lines += [
            "",
            "─" * 70,
            f"  WARNINGS ({len(warnings_lines)})",
            "─" * 70,
        ]
        lines += [f"  {w}" for w in warnings_lines]

    if error_lines:
        lines += [
            "",
            "─" * 70,
            f"  ERRORS ({len(error_lines)})",
            "─" * 70,
        ]
        lines += [f"  {e}" for e in error_lines]

    lines += [
        "",
        "─" * 70,
        "  FULL LOG",
        "─" * 70,
    ]
    lines += [f"  {l}" for l in result.log_lines[-200:]]
    lines += ["", "=" * 70, ""]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# HTML validation report
# ─────────────────────────────────────────────────────────────────────────────

_LEVEL_CSS = {
    "error": ("var(--c-error)", "var(--c-error-bg)", "ERROR"),
    "warning": ("var(--c-warn)", "var(--c-warn-bg)", "WARN"),
    "info": ("var(--c-info)", "var(--c-info-bg)", "INFO"),
    "pass": ("var(--c-pass)", "var(--c-pass-bg)", "PASS"),
}

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Validation Report — {escaped_filename}</title>
<style>
  :root{{
    --c-error:#b91c1c; --c-error-bg:#fef2f2;
    --c-warn:#92400e;  --c-warn-bg:#fffbeb;
    --c-info:#1d4ed8;  --c-info-bg:#eff6ff;
    --c-pass:#166534;  --c-pass-bg:#f0fdf4;
    --border:#e5e7eb; --bg:#f9fafb; --card:#fff;
    --text:#111827; --muted:#6b7280;
    font-family: system-ui, -apple-system, sans-serif;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--text);padding:2rem 1rem}}
  .wrap{{max-width:960px;margin:0 auto}}
  header{{margin-bottom:2rem}}
  h1{{font-size:1.5rem;font-weight:700;margin-bottom:.25rem}}
  h2{{font-size:1rem;font-weight:700;margin:1.5rem 0 .75rem}}
  .meta{{color:var(--muted);font-size:.875rem}}
  .summary{{display:flex;flex-wrap:wrap;gap:.75rem;margin-bottom:1.5rem}}
  .stat{{border-radius:.5rem;padding:.75rem 1.25rem;border:1px solid var(--border);
         text-align:center;min-width:100px;flex:1}}
  .stat .n{{font-size:1.75rem;font-weight:700;line-height:1}}
  .stat .label{{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;
                color:var(--muted);margin-top:.25rem}}
  .stat.error{{background:var(--c-error-bg);border-color:var(--c-error);color:var(--c-error)}}
  .stat.warn {{background:var(--c-warn-bg); border-color:var(--c-warn); color:var(--c-warn)}}
  .stat.info {{background:var(--c-info-bg); border-color:var(--c-info); color:var(--c-info)}}
  .stat.pass {{background:var(--c-pass-bg); border-color:var(--c-pass); color:var(--c-pass)}}
  .banner{{border-radius:.5rem;padding:.75rem 1rem;margin-bottom:1.5rem;font-size:.875rem;font-weight:600}}
  .banner.ok{{background:var(--c-pass-bg);border:1px solid var(--c-pass);color:var(--c-pass)}}
  .banner.blocked{{background:var(--c-error-bg);border:1px solid var(--c-error);color:var(--c-error)}}
  .stats-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));
               gap:.75rem;margin-bottom:1.5rem}}
  .stats-card{{background:var(--card);border:1px solid var(--border);border-radius:.5rem;
               padding:.75rem 1rem}}
  .stats-card .sc-label{{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;
                          color:var(--muted);margin-bottom:.25rem}}
  .stats-card .sc-value{{font-size:1.1rem;font-weight:700}}
  .controls{{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center;margin-bottom:1rem}}
  #search{{flex:1;min-width:180px;padding:.45rem .75rem;border:1px solid var(--border);
           border-radius:.375rem;font-size:.875rem;outline:none}}
  #search:focus{{border-color:#6366f1;box-shadow:0 0 0 3px rgba(99,102,241,.15)}}
  .filters{{display:flex;gap:.375rem;flex-wrap:wrap}}
  .filter-btn{{padding:.3rem .7rem;border-radius:.375rem;border:1px solid var(--border);
               background:var(--card);font-size:.75rem;cursor:pointer;transition:.15s}}
  .filter-btn:hover{{background:#f3f4f6}}
  .filter-btn.active{{background:#1e293b;color:#fff;border-color:#1e293b}}
  .filter-btn[data-level="error"].active{{background:var(--c-error);border-color:var(--c-error)}}
  .filter-btn[data-level="warning"].active{{background:var(--c-warn);border-color:var(--c-warn)}}
  .filter-btn[data-level="info"].active{{background:var(--c-info);border-color:var(--c-info)}}
  .filter-btn[data-level="pass"].active{{background:var(--c-pass);border-color:var(--c-pass)}}
  #no-results{{display:none;text-align:center;padding:3rem;color:var(--muted)}}
  .section{{margin-bottom:1.5rem}}
  .section-title{{font-size:.75rem;font-weight:700;text-transform:uppercase;
                  letter-spacing:.06em;color:var(--muted);margin-bottom:.5rem;padding-left:.25rem}}
  .issue{{background:var(--card);border:1px solid var(--border);border-radius:.5rem;
          margin-bottom:.5rem;overflow:hidden;transition:.15s}}
  .issue:hover{{border-color:#d1d5db}}
  .issue-header{{display:flex;align-items:flex-start;gap:.75rem;padding:.75rem 1rem;cursor:pointer;
                 user-select:none}}
  .badge{{border-radius:.25rem;padding:.15rem .4rem;font-size:.65rem;font-weight:700;
          letter-spacing:.04em;white-space:nowrap;flex-shrink:0;margin-top:.1rem}}
  .badge.error{{background:var(--c-error-bg);color:var(--c-error)}}
  .badge.warn {{background:var(--c-warn-bg); color:var(--c-warn)}}
  .badge.info {{background:var(--c-info-bg); color:var(--c-info)}}
  .badge.pass {{background:var(--c-pass-bg); color:var(--c-pass)}}
  .issue-title{{flex:1;min-width:0}}
  .issue-title strong{{font-size:.875rem;display:block}}
  .issue-title p{{font-size:.8rem;color:var(--muted);margin-top:.15rem;line-height:1.4}}
  .count-pill{{font-size:.7rem;font-family:monospace;background:#f3f4f6;
               border-radius:.25rem;padding:.1rem .4rem;color:var(--muted);flex-shrink:0}}
  .chevron{{flex-shrink:0;color:var(--muted);transition:transform .2s;font-size:.85rem}}
  .issue-body{{display:none;padding:.5rem 1rem .75rem 1rem;border-top:1px solid var(--border)}}
  .issue-body.open{{display:block}}
  .detail-list{{list-style:none;font-family:monospace;font-size:.75rem;color:var(--muted)}}
  .detail-list li{{padding:.1rem 0;display:flex;gap:.5rem}}
  .detail-list li:before{{content:attr(data-n);color:#d1d5db;width:1.5rem;text-align:right;flex-shrink:0}}
  .more{{font-style:italic;color:#9ca3af;margin-top:.25rem}}
  footer{{margin-top:3rem;font-size:.75rem;color:var(--muted);text-align:center}}
  @media(max-width:600px){{.summary{{grid-template-columns:1fr 1fr}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Shopify → WooCommerce Validation Report</h1>
  <p class="meta">File: <strong>{escaped_filename}</strong> &nbsp;·&nbsp; Generated: {timestamp}</p>
</header>

<div class="summary">
  <div class="stat error"><div class="n">{error_count}</div><div class="label">Errors</div></div>
  <div class="stat warn"><div class="n">{warning_count}</div><div class="label">Warnings</div></div>
  <div class="stat info"><div class="n">{info_count}</div><div class="label">Info</div></div>
  <div class="stat pass"><div class="n">{pass_count}</div><div class="label">Passed</div></div>
</div>

<div class="banner {banner_cls}">{banner_msg}</div>

{stats_section}

<div class="controls">
  <input id="search" type="search" placeholder="Search checks…" oninput="applyFilters()">
  <div class="filters">
    <button class="filter-btn active" data-level="all" onclick="setLevel('all')">All</button>
    <button class="filter-btn" data-level="error" onclick="setLevel('error')">Errors</button>
    <button class="filter-btn" data-level="warning" onclick="setLevel('warning')">Warnings</button>
    <button class="filter-btn" data-level="info" onclick="setLevel('info')">Info</button>
    <button class="filter-btn" data-level="pass" onclick="setLevel('pass')">Passed</button>
  </div>
</div>

<div id="issues-list">
{issues_html}
</div>
<div id="no-results">No matching checks.</div>

<footer>Generated by Shopify → WooCommerce Converter &nbsp;·&nbsp; {timestamp}</footer>
</div>

<script>
let activeLevel = 'all';
function setLevel(l){{
  activeLevel = l;
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.toggle('active', b.dataset.level===l));
  applyFilters();
}}
function applyFilters(){{
  const q = document.getElementById('search').value.toLowerCase();
  let visible = 0;
  document.querySelectorAll('.issue').forEach(el=>{{
    const lvl = el.dataset.level;
    const txt = el.textContent.toLowerCase();
    const levelOk = activeLevel==='all' || lvl===activeLevel;
    const searchOk = !q || txt.includes(q);
    el.style.display = (levelOk && searchOk) ? '' : 'none';
    if(levelOk && searchOk) visible++;
  }});
  document.getElementById('no-results').style.display = visible ? 'none' : 'block';
}}
document.querySelectorAll('.issue-header').forEach(h=>{{
  h.addEventListener('click',()=>{{
    const body = h.nextElementSibling;
    if(!body) return;
    body.classList.toggle('open');
    const ch = h.querySelector('.chevron');
    if(ch) ch.textContent = body.classList.contains('open') ? '▲' : '▼';
  }});
}});
</script>
</body>
</html>
"""


def _build_stats_section(result: ValidationResult) -> str:
    """
    Extract key stats (product count, variant count, product type breakdown,
    attribute names) from the info-level issues and render a dashboard card row.
    """
    csv_stats_msg = ""
    type_breakdown_msg = ""
    attr_mapping_msg = ""
    simple_count = ""
    variable_count = ""
    attr_count = ""

    for issue in result.issues:
        if issue.check == "CSV Statistics":
            csv_stats_msg = issue.message
        elif issue.check == "Product Type Breakdown":
            type_breakdown_msg = issue.message
            for d in issue.details:
                if d.startswith("Simple:"):
                    simple_count = d.split(":", 1)[1].strip()
                elif d.startswith("Variable:"):
                    variable_count = d.split(":", 1)[1].strip()
        elif issue.check == "Attribute Mapping":
            attr_count = str(issue.count)

    if not csv_stats_msg and not type_breakdown_msg:
        return ""

    cards: list[str] = []

    if simple_count or variable_count:
        cards.append(
            f'<div class="stats-card">'
            f'<div class="sc-label">Simple Products</div>'
            f'<div class="sc-value">{html_module.escape(simple_count or "—")}</div>'
            f'</div>'
        )
        cards.append(
            f'<div class="stats-card">'
            f'<div class="sc-label">Variable Products</div>'
            f'<div class="sc-value">{html_module.escape(variable_count or "—")}</div>'
            f'</div>'
        )

    if attr_count:
        cards.append(
            f'<div class="stats-card">'
            f'<div class="sc-label">Distinct Attributes</div>'
            f'<div class="sc-value">{html_module.escape(attr_count)}</div>'
            f'</div>'
        )

    if not cards:
        return ""

    return (
        f'<h2>CSV Statistics</h2>'
        f'<div class="stats-grid">{"".join(cards)}</div>'
    )


def _render_issue(issue_data: dict) -> str:
    level = issue_data["level"]
    badge_cls = {"error": "error", "warning": "warn", "info": "info", "pass": "pass"}.get(level, "pass")
    badge_label = {"error": "ERROR", "warning": "WARN", "info": "INFO", "pass": "PASS"}.get(level, level.upper())

    chevron = "▼" if issue_data["details"] else ""
    count_pill = (
        f'<span class="count-pill">{issue_data["count"]}</span>'
        if issue_data["count"] > 0 else ""
    )

    details_html = ""
    if issue_data["details"]:
        items = "".join(
            f'<li data-n="{i + 1}">{html_module.escape(d)}</li>'
            for i, d in enumerate(issue_data["details"][:20])
        )
        more = ""
        if len(issue_data["details"]) > 20:
            more = f'<p class="more">…and {len(issue_data["details"]) - 20} more</p>'
        details_html = f'<ul class="detail-list">{items}</ul>{more}'

    return (
        f'<div class="issue" data-level="{level}">'
        f'<div class="issue-header">'
        f'<span class="badge {badge_cls}">{badge_label}</span>'
        f'<div class="issue-title">'
        f'<strong>{html_module.escape(issue_data["check"])}</strong>'
        f'<p>{html_module.escape(issue_data["message"])}</p>'
        f'</div>'
        f'{count_pill}'
        f'<span class="chevron">{chevron}</span>'
        f'</div>'
        f'<div class="issue-body">{details_html}</div>'
        f'</div>'
    )


def generate_validation_html(
    filename: str,
    result: ValidationResult,
    output_path: str,
) -> None:
    escaped_filename = html_module.escape(filename)
    timestamp = _now()

    banner_cls = "ok" if result.can_convert else "blocked"
    if result.can_convert:
        banner_msg = (
            f"✓ Validation passed — file is ready to convert. "
            f"({result.warning_count} warning(s), {result.info_count} informational note(s).)"
        )
    else:
        banner_msg = (
            f"✗ Conversion blocked — {result.error_count} error(s) must be resolved before converting."
        )

    stats_section = _build_stats_section(result)

    # Group issues by level for ordered rendering
    order = ["error", "warning", "info", "pass"]
    by_level: dict[str, list] = {k: [] for k in order}
    for issue in result.issues:
        by_level.get(issue.level, by_level["info"]).append(issue)

    sections: list[str] = []
    section_labels = {
        "error": "🔴 Errors — Block Conversion",
        "warning": "🟡 Warnings — Review Recommended",
        "info": "🔵 Informational",
        "pass": "✅ Passed Checks",
    }
    for lvl in order:
        grp = by_level[lvl]
        if not grp:
            continue
        rendered = "\n".join(
            _render_issue({
                "level": issue.level,
                "check": issue.check,
                "message": issue.message,
                "count": issue.count,
                "details": issue.details,
            })
            for issue in grp
        )
        sections.append(
            f'<div class="section">'
            f'<div class="section-title">{section_labels[lvl]} ({len(grp)})</div>'
            f'{rendered}'
            f'</div>'
        )

    issues_html = "\n".join(sections)

    content = _HTML_TEMPLATE.format(
        escaped_filename=escaped_filename,
        timestamp=timestamp,
        error_count=result.error_count,
        warning_count=result.warning_count,
        info_count=result.info_count,
        pass_count=result.pass_count,
        banner_cls=banner_cls,
        banner_msg=banner_msg,
        stats_section=stats_section,
        issues_html=issues_html,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


# ─────────────────────────────────────────────────────────────────────────────
# Conversion log
# ─────────────────────────────────────────────────────────────────────────────

def generate_conversion_log(log_lines: list[str], output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines))
        f.write("\n")
