from pathlib import Path
from uuid import uuid4

import matplotlib
import pandas as pd

from .files import write_json

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter, StrMethodFormatter


def atomic_frame(frame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        if path.suffix == ".parquet":
            frame.to_parquet(temporary, engine="pyarrow", index=False)
        else:
            frame.to_csv(temporary, index=False, encoding="utf-8-sig")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def export_clean(data, root):
    for field, entries in (("products", data.books), ("exchange_rates", data.rates)):
        frame = pd.DataFrame([entry.model_dump() for entry in entries])
        frame["collected_at"] = pd.to_datetime(frame["collected_at"], utc=True)
        if field == "products":
            frame["rating"] = frame["rating"].astype("Int64")
            frame["in_stock"] = frame["in_stock"].astype("boolean")
        atomic_frame(frame, root / "clean" / f"{field}.parquet")


def make_charts(categories, sensitivity, root, budget):
    biggest = categories.sort_values(["products", "category"], ascending=[False, True]).head(8)
    ordered = biggest.sort_values("median_rub")
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": "white"})
    fig, ax = plt.subplots(figsize=(8.6, 4.3), layout="constrained")
    color = "#176078"
    bars = ax.barh(ordered["category"], ordered["median_rub"], color=color, height=0.63)
    ax.bar_label(bars, labels=[f"{value:,.0f}".replace(",", " ") for value in ordered["median_rub"]],
                 padding=5, color="#1c2635", fontsize=10)
    ax.set_title("Медианная цена по восьми крупнейшим категориям", loc="left", pad=13)
    ax.set_xlabel("Рубли за книгу")
    ax.set_xlim(0, ordered["median_rub"].max() * 1.20)
    ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    ax.set_axisbelow(True)
    ax.grid(axis="x", alpha=0.2)
    fig.savefig(root / "category_prices.png", dpi=175)
    plt.close(fig)

    scenarios = sensitivity[sensitivity["scenario"].isin(["lower", "current", "higher"])]
    scenarios = scenarios.pivot(index="category", columns="scenario", values="budget_share")
    scenarios = scenarios.reindex(biggest.head(6)["category"])[["lower", "current", "higher"]]
    fig, ax = plt.subplots(figsize=(8.6, 4.3), layout="constrained")
    scenarios.iloc[::-1].plot.barh(ax=ax, color=["#91c7d2", "#176078", "#af5b2b"], width=0.78)
    ax.set_title(f"Доля книг в бюджете {budget:,.0f} ₽".replace(",", " "), loc="left", pad=13)
    ax.set_xlabel("Доля книг в категории")
    ax.set_ylabel("")
    ax.set_xlim(0, 1)
    ax.xaxis.set_major_formatter(PercentFormatter(1))
    ax.set_axisbelow(True)
    ax.grid(axis="x", alpha=0.2)
    ax.legend(["Снижение курса", "Текущий курс", "Рост курса"], frameon=False,
              loc="upper center", bbox_to_anchor=(0.5, -0.17), ncols=3, fontsize=9)
    fig.savefig(root / "budget_sensitivity.png", dpi=175)
    plt.close(fig)


def build_mart(db, root, current_rate, budget, sensitivity_percent):
    folder = root / "mart"
    folder.mkdir(parents=True, exist_ok=True)
    products = pd.read_sql_query(
        "SELECT * FROM priced_catalogue WHERE rate_date = ? ORDER BY source_id",
        db, params=(current_rate.rate_date.isoformat(),),
    )
    products["price_gbp"] = products["price_pence"] / 100
    products["price_rub"] = products["price_rub_kopeks"] / 100
    products["within_budget"] = products["price_rub_kopeks"] <= budget * 100
    products["collected_at"] = pd.to_datetime(products["collected_at"], utc=True)
    products["rate_date"] = pd.to_datetime(products["rate_date"]).dt.date
    products["in_stock"] = products["in_stock"].astype("boolean")
    products["rating"] = products["rating"].astype("Int64")
    atomic_frame(products, folder / "priced_catalogue.parquet")
    categories = products.groupby("category", as_index=False).agg(
        products=("business_key", "size"),
        median_gbp=("price_gbp", "median"),
        median_rub=("price_rub", "median"),
        budget_count=("within_budget", "sum"),
        budget_share=("within_budget", "mean"),
    )
    categories = categories.sort_values(["products", "category"], ascending=[False, True])
    atomic_frame(categories, folder / "category_prices.csv")

    scenarios = [("current", current_rate.rate_date.isoformat(), current_rate.rub_x10000)]
    previous = db.execute(
        "SELECT rate_date, rub_x10000 FROM exchange_rates WHERE currency = ? AND rate_date < ? "
        "ORDER BY rate_date DESC LIMIT 1",
        (current_rate.currency, current_rate.rate_date.isoformat()),
    ).fetchone()
    if previous:
        scenarios.insert(0, ("previous", *previous))
    scenarios.extend((
        ("lower", None, (current_rate.rub_x10000 * (100 - sensitivity_percent) + 50) // 100),
        ("higher", None, (current_rate.rub_x10000 * (100 + sensitivity_percent) + 50) // 100),
    ))

    grouped = []
    totals = {}
    for name, day, rate in scenarios:
        price = (products["price_pence"] * rate + 5000) // 10000
        within = price <= budget * 100
        work = products[["category"]].assign(rub=price / 100, within=within)
        compared = work.groupby("category", as_index=False).agg(
            products=("rub", "size"), median_rub=("rub", "median"),
            budget_count=("within", "sum"), budget_share=("within", "mean"),
        )
        grouped.append(compared.assign(scenario=name, rate_date=day, rub_per_gbp=rate / 10000))
        totals[name] = {
            "rate_date": day,
            "rub_per_gbp": rate / 10000,
            "budget_count": int(within.sum()),
            "budget_share": round(float(within.mean()), 6),
            "median_rub": round(float(price.median() / 100), 2),
        }
    sensitivity = pd.concat(grouped, ignore_index=True)
    atomic_frame(sensitivity, folder / "budget_sensitivity.csv")
    make_charts(categories, sensitivity, folder, budget)

    summary = {
        "products": len(products),
        "categories": len(categories),
        "budget_rub": budget,
        "sensitivity_percent": sensitivity_percent,
        "top_categories": categories.head(8).round(6).to_dict("records"),
        "scenarios": totals,
    }
    write_json(folder / "analytic_summary.json", summary)
    return summary
