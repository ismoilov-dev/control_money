"""Chart generation utility using matplotlib for FinMate Bot."""

from __future__ import annotations

import io
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt


def generate_category_pie_chart(category_totals: dict[str, int], title: str = "Xarajatlar tarkibi") -> bytes | None:
    """Generate pie chart image bytes from category totals dict."""
    if not category_totals:
        return None

    labels = []
    sizes = []
    for cat, amount in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
        if amount > 0:
            labels.append(f"{cat}\n({amount:,} so'm)".replace(",", " "))
            sizes.append(amount)

    if not sizes:
        return None

    # Modern color palette
    colors = [
        "#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A",
        "#98D8C8", "#F7DC6F", "#BB8FCE", "#85929E",
        "#F1948A", "#82E0AA", "#F8C471", "#D7BDE2"
    ]

    plt.figure(figsize=(7, 7), facecolor="#ffffff")
    plt.style.use("ggplot")

    wedges, texts, autotexts = plt.pie(
        sizes,
        labels=labels,
        autopct="%1.1f%%",
        startangle=140,
        colors=colors[:len(sizes)],
        pctdistance=0.75,
        wedgeprops=dict(width=0.4, edgecolor="w", linewidth=2),
    )

    plt.setp(autotexts, size=10, weight="bold", color="black")
    plt.setp(texts, size=10)
    plt.title(title, fontsize=14, fontweight="bold", pad=20)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=150)
    plt.close()
    buf.seek(0)
    return buf.getvalue()
