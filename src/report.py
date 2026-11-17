"""
Builds a self-contained HTML report with charts from the pipeline output.

It stands in for the Power BI dashboard in this public repo: anyone can open it without a
Power BI licence, and it is regenerated from the same `data/processed/` files.

Gebruik:
    python -m src.report                     # leest de laatste run, schrijft docs/report/
    python -m src.report --out site/         # andere doelmap
"""

from __future__ import annotations

import argparse
import base64
import html
import io
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

SEGMENT_ORDER = ["Champions", "Potentials", "At Risk", "Lost"]
SEGMENT_COLORS = {
    "Champions": "#2e7d5b",
    "Potentials": "#3b6fb6",
    "At Risk": "#d98a1c",
    "Lost": "#b8433a",
}
INK = "#1d2430"
MUTED = "#6b7280"
GRID = "#e5e7eb"


def latest_segmented_file(processed_dir: Path) -> Path:
    files = sorted(processed_dir.glob("employers_segmented_*.csv"))
    if not files:
        raise FileNotFoundError(f"No employers_segmented_*.csv in {processed_dir}. Run `python -m src.main` first.")
    return files[-1]


def _style(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.yaxis.label.set_color(MUTED)
    ax.xaxis.label.set_color(MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _to_data_uri(fig: plt.Figure) -> str:
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def chart_segment_overview(df: pd.DataFrame) -> plt.Figure:
    """Count and total revenue potential per segment, side by side."""
    stats = (
        df.groupby("segment_name")
        .agg(count=("employer_id", "count"), revenue=("revenue_potential", "sum"))
        .reindex(SEGMENT_ORDER)
    )
    colors = [SEGMENT_COLORS[s] for s in stats.index]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    axes[0].bar(stats.index, stats["count"], color=colors, width=0.62)
    axes[0].set_title("Employers per segment", loc="left", color=INK, fontsize=11, fontweight="bold")
    axes[1].bar(stats.index, stats["revenue"] / 1e6, color=colors, width=0.62)
    axes[1].set_title("Revenue potential per segment (€ M)", loc="left", color=INK, fontsize=11, fontweight="bold")
    for ax, column, fmt in ((axes[0], "count", "{:.0f}"), (axes[1], "revenue", "€{:.1f}M")):
        _style(ax)
        for i, value in enumerate(stats[column]):
            label = fmt.format(value / 1e6 if column == "revenue" else value)
            ax.annotate(label, (i, value / (1e6 if column == "revenue" else 1)), ha="center", va="bottom",
                        fontsize=9, color=INK, xytext=(0, 3), textcoords="offset points")
    fig.tight_layout()
    return fig


def chart_rfm_map(df: pd.DataFrame) -> plt.Figure:
    """Recency vs. contact frequency; bubble size = revenue potential."""
    fig, ax = plt.subplots(figsize=(10, 4.6))
    size = 12 + 220 * (df["revenue_potential"] / df["revenue_potential"].max())
    for segment in SEGMENT_ORDER:
        part = df[df["segment_name"] == segment]
        ax.scatter(part["recency_days"], part["frequency_12m"], s=size[part.index], alpha=0.55,
                   color=SEGMENT_COLORS[segment], edgecolors="white", linewidths=0.5, label=f"{segment} ({len(part)})")
    ax.set_xlabel("Days since last contact")
    ax.set_ylabel("Contacts in the last 12 months")
    ax.set_title("Who is drifting away? Each dot is an employer; size = revenue potential",
                 loc="left", color=INK, fontsize=11, fontweight="bold")
    _style(ax)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    legend = ax.legend(frameon=False, fontsize=9, loc="upper right", markerscale=0.6)
    for text in legend.get_texts():
        text.set_color(INK)
    fig.tight_layout()
    return fig


def call_list(df: pd.DataFrame, limit: int = 15) -> pd.DataFrame:
    """
    The account managers' list for this week: At Risk employers with the most revenue at stake.
    Pseudonymised IDs only — the CRM resolves an ID to a contact person.
    """
    at_risk = df[df["segment_name"] == "At Risk"]
    columns = ["employer_id", "sector", "company_size", "region", "recency_days", "frequency_12m", "revenue_potential"]
    return at_risk.sort_values("revenue_potential", ascending=False)[columns].head(limit).reset_index(drop=True)


def build_html(df: pd.DataFrame, profiles: pd.DataFrame, generated_on: date) -> str:
    total = len(df)
    shares = df["segment_name"].value_counts().reindex(SEGMENT_ORDER).fillna(0).astype(int)
    at_risk_revenue = df.loc[df["segment_name"] == "At Risk", "revenue_potential"].sum()
    calls = call_list(df)

    cards = "".join(
        f'<div class="kpi" style="--c:{SEGMENT_COLORS[s]}"><span>{s}</span><b>{shares[s]}</b>'
        f"<small>{shares[s] / total:.0%} of portfolio</small></div>"
        for s in SEGMENT_ORDER
    )
    profile_rows = "".join(
        f"<tr><td><i style='background:{SEGMENT_COLORS[r.segment_name]}'></i>{html.escape(r.segment_name)}</td>"
        f"<td>{r.count}</td><td>€{r.avg_revenue_potential:,.0f}</td><td>{r.avg_priority_score:.0f}</td>"
        f"<td>{r.avg_rfm_score:.2f}</td></tr>"
        for r in profiles.itertuples()
    )
    call_rows = "".join(
        f"<tr><td><code>{html.escape(r.employer_id)}</code></td><td>{html.escape(str(r.sector))}</td>"
        f"<td>{html.escape(str(r.company_size))}</td><td>{html.escape(str(r.region))}</td>"
        f"<td>{r.recency_days} d</td><td>{r.frequency_12m}</td><td>€{r.revenue_potential:,.0f}</td></tr>"
        for r in calls.itertuples()
    )
    overview = _to_data_uri(chart_segment_overview(df))
    rfm = _to_data_uri(chart_rfm_map(df))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Employer segmentation report</title>
<style>
:root{{--ink:{INK};--muted:{MUTED};--line:{GRID};--bg:#f7f7f5}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,"Segoe UI",Inter,Roboto,sans-serif}}
.wrap{{max-width:1040px;margin:0 auto;padding:36px 16px 60px}}
.eyebrow{{font:700 12px/1 sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}}
h1{{font-size:clamp(26px,4vw,36px);margin:8px 0 6px;letter-spacing:-.02em}}h2{{margin:34px 0 12px;font-size:19px}}
.lede{{color:var(--muted);max-width:70ch;margin:0}}
.finding{{margin:22px 0;padding:16px 18px;background:#fff7ea;border-left:4px solid {SEGMENT_COLORS["At Risk"]};border-radius:10px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}}
.kpi{{background:#fff;border:1px solid var(--line);border-top:4px solid var(--c);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column}}
.kpi span{{font-weight:600}}.kpi b{{font-size:30px;line-height:1.2}}.kpi small{{color:var(--muted)}}
figure{{margin:0;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px}}figure img{{width:100%;height:auto;display:block}}
figcaption{{color:var(--muted);font-size:13px;margin-top:8px}}
.table{{overflow-x:auto;background:#fff;border:1px solid var(--line);border-radius:12px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap}}
th{{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em}}tr:last-child td{{border:0}}
td i{{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:8px}}code{{font-size:13px}}
footer{{margin-top:40px;color:var(--muted);font-size:13px}}
</style></head><body><div class="wrap">
<p class="eyebrow">HR analytics · employer segmentation · generated {generated_on:%d %b %Y}</p>
<h1>Who to call first, and why</h1>
<p class="lede">RFM scoring (recency, frequency, revenue potential) and K-Means clustering on {total:,} employers.
Synthetic, seeded demo data — the same pipeline runs on a CRM export.</p>
<div class="finding"><b>Key finding:</b> {shares["At Risk"]} employers ({shares["At Risk"] / total:.0%}) were once active but contact has gone quiet.
Together they represent <b>€{at_risk_revenue / 1e6:.1f}M</b> in revenue potential — the largest short-term recovery opportunity.</div>
<div class="kpis">{cards}</div>
<h2>Segments at a glance</h2>
<figure><img src="{overview}" alt="Bar charts: number of employers and total revenue potential per segment"></figure>
<h2>The RFM map</h2>
<figure><img src="{rfm}" alt="Scatter plot of days since last contact against contacts in the last 12 months, coloured by segment">
<figcaption>Bottom-right is where relationships go cold: long since last contact, few contacts this year.</figcaption></figure>
<h2>Segment profiles</h2>
<div class="table"><table><thead><tr><th>Segment</th><th>Employers</th><th>Avg revenue potential</th><th>Avg priority (0–100)</th><th>Avg RFM</th></tr></thead>
<tbody>{profile_rows}</tbody></table></div>
<h2>This week's call list</h2>
<p class="lede">At Risk employers with the most revenue at stake. IDs are pseudonymised by the pipeline before analysis; the CRM resolves an ID to a contact person.</p>
<div class="table"><table><thead><tr><th>Employer</th><th>Sector</th><th>Size</th><th>Region</th><th>Last contact</th><th>Contacts 12m</th><th>Revenue potential</th></tr></thead>
<tbody>{call_rows}</tbody></table></div>
<footer>Generated by <code>python -m src.report</code> from <a href="https://github.com/phlppgdfry/hr-analytics-segmentation">hr-analytics-segmentation</a>.
Stands in for the Power BI dashboard described in <code>powerbi/</code>.</footer>
</div></body></html>"""


def write_report(processed_dir: Path, out_dir: Path, generated_on: date | None = None) -> Path:
    df = pd.read_csv(latest_segmented_file(processed_dir))
    profiles = pd.read_csv(processed_dir / "segment_profiles.csv")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "index.html"
    target.write_text(build_html(df, profiles, generated_on or date.today()), encoding="utf-8")
    # Standalone chart files for the README.
    chart_segment_overview(df).savefig(out_dir / "segments.png", dpi=160, bbox_inches="tight", facecolor="white")
    chart_rfm_map(df).savefig(out_dir / "rfm-map.png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close("all")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the HTML segmentation report")
    parser.add_argument("--processed", type=Path, default=Path("data/processed"))
    parser.add_argument("--out", type=Path, default=Path("docs/report"))
    args = parser.parse_args()
    path = write_report(args.processed, args.out)
    print(f"✅ Report written to {path}")


if __name__ == "__main__":
    main()
