import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
from datetime import date, timedelta, datetime
from collections import defaultdict

from transactions import TRANSACTIONS, CURRENT_POSITIONS, STOCK_INFO

st.set_page_config(page_title="포트폴리오 트래커", page_icon="📈", layout="wide")

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def fmt_krw(v):
    return f"₩{int(v):,}"

def fmt_pct(v):
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"

def fmt_usd(v):
    return f"${v:,.0f}"


@st.cache_data(ttl=60, show_spinner=False)
def fetch_realtime(code: str) -> dict | None:
    url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
    try:
        r = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            d = r.json().get("datas", [{}])[0]
            over = d.get("overMarketPriceInfo", {})
            over_price = over.get("overPrice", "")
            close_raw = d.get("closePriceRaw", 0)
            if over_price and str(over_price).replace(",", "").isdigit():
                price = int(str(over_price).replace(",", ""))
            else:
                price = int(close_raw) if close_raw else 0
            prev = int(str(d.get("stockExchangeType", {}) and d.get("compareToPreviousClosePrice", close_raw)).replace(",", "") or close_raw)
            return {"price": price, "close": int(close_raw)}
    except Exception:
        pass
    return None


def apply_fifo(lots: list, sell_shares: float) -> tuple[list, list]:
    """Remove sell_shares from lots (FIFO). Returns (remaining_lots, consumed_lots)."""
    remaining = sell_shares
    consumed = []
    new_lots = []
    for lot in lots:
        if remaining <= 0:
            new_lots.append(lot)
            continue
        take = min(lot["shares"], remaining)
        if take > 0:
            consumed.append({**lot, "shares": take})
        if lot["shares"] - take > 1e-6:
            new_lots.append({**lot, "shares": lot["shares"] - take})
        remaining -= take
    return new_lots, consumed


def compute_lots_at(owner: str, code: str, up_to: str = "9999-99-99") -> list:
    """Returns FIFO lots for (owner, code) up to given date."""
    lots = []
    for t in sorted(TRANSACTIONS, key=lambda x: x["date"]):
        if t["date"] > up_to:
            break
        if t["owner"] != owner or t["code"] != code:
            continue
        if t["type"] == "buy":
            lots.append({"date": t["date"], "shares": float(t["shares"]), "price": float(t["price"])})
        elif t["type"] == "sell":
            lots, _ = apply_fifo(lots, float(t["shares"]))
        elif t["type"] == "split":
            ratio = float(t["new_shares"]) / float(t["old_shares"])
            lots = [{"date": l["date"], "shares": l["shares"] * ratio, "price": l["price"] / ratio} for l in lots]
    return lots


def compute_realized_gains(owner_filter=None, year_filter=None) -> list:
    """Compute all realized gain events using FIFO."""
    pairs = {}
    for t in TRANSACTIONS:
        key = (t["owner"], t["code"])
        if key not in pairs:
            pairs[key] = {"name": t["name"], "lots": [], "events": []}

    pairs = {}
    for t in sorted(TRANSACTIONS, key=lambda x: x["date"]):
        key = (t["owner"], t["code"])
        if key not in pairs:
            pairs[key] = {"name": t["name"], "lots": []}

        if owner_filter and t["owner"] != owner_filter:
            continue
        if key not in pairs:
            pairs[key] = {"name": t["name"], "lots": []}

    realized = []
    lots_state = {}

    for t in sorted(TRANSACTIONS, key=lambda x: x["date"]):
        key = (t["owner"], t["code"])
        if key not in lots_state:
            lots_state[key] = []

        if t["type"] == "buy":
            lots_state[key].append({"date": t["date"], "shares": float(t["shares"]), "price": float(t["price"])})

        elif t["type"] == "sell":
            if owner_filter and t["owner"] != owner_filter:
                continue
            sell_date = t["date"]
            sell_price = float(t["price"])
            remaining = float(t["shares"])
            lots = lots_state[key]

            for lot in lots:
                if remaining <= 1e-6:
                    break
                take = min(lot["shares"], remaining)
                buy_dt = datetime.strptime(lot["date"], "%Y-%m-%d").date()
                sell_dt = datetime.strptime(sell_date, "%Y-%m-%d").date()
                days = (sell_dt - buy_dt).days
                yr = int(sell_date[:4])
                event = {
                    "owner": t["owner"],
                    "code": t["code"],
                    "name": t["name"],
                    "buy_date": lot["date"],
                    "sell_date": sell_date,
                    "shares": take,
                    "cost_per_share": lot["price"],
                    "sell_per_share": sell_price,
                    "cost": lot["price"] * take,
                    "proceeds": sell_price * take,
                    "gain": (sell_price - lot["price"]) * take,
                    "holding_days": days,
                    "is_lt": days >= 365,
                    "year": yr,
                }
                realized.append(event)
                remaining -= take

            lots_state[key], _ = apply_fifo(lots_state[key], float(t["shares"]))

        elif t["type"] == "split":
            ratio = float(t["new_shares"]) / float(t["old_shares"])
            lots_state[key] = [
                {"date": l["date"], "shares": l["shares"] * ratio, "price": l["price"] / ratio}
                for l in lots_state[key]
            ]

    if year_filter:
        realized = [r for r in realized if r["year"] == year_filter]
    return realized


def compute_holdings_at(date_str: str, owner_filter=None) -> list:
    """Compute all holdings at a given date from transactions."""
    lots_state = {}
    name_map = {}
    for t in sorted(TRANSACTIONS, key=lambda x: x["date"]):
        if t["date"] > date_str:
            break
        key = (t["owner"], t["code"])
        name_map[key] = t["name"]
        if key not in lots_state:
            lots_state[key] = []

        if t["type"] == "buy":
            lots_state[key].append({"date": t["date"], "shares": float(t["shares"]), "price": float(t["price"])})
        elif t["type"] == "sell":
            lots_state[key], _ = apply_fifo(lots_state[key], float(t["shares"]))
        elif t["type"] == "split":
            ratio = float(t["new_shares"]) / float(t["old_shares"])
            lots_state[key] = [
                {"date": l["date"], "shares": l["shares"] * ratio, "price": l["price"] / ratio}
                for l in lots_state[key]
            ]

    rows = []
    for (owner, code), lots in lots_state.items():
        if owner_filter and owner != owner_filter:
            continue
        total_shares = sum(l["shares"] for l in lots)
        if total_shares < 0.01:
            continue
        total_cost = sum(l["shares"] * l["price"] for l in lots)
        rows.append({
            "owner": owner,
            "code": code,
            "name": name_map.get((owner, code), code),
            "shares": total_shares,
            "avg_price": total_cost / total_shares,
            "total_cost": total_cost,
        })
    return rows


def cumulative_cashflow() -> pd.DataFrame:
    """Returns daily cumulative net cash invested (buys - sells) per owner."""
    events = []
    for t in TRANSACTIONS:
        if t["type"] not in ("buy", "sell"):
            continue
        flow = float(t["price"]) * float(t["shares"])
        if t["type"] == "sell":
            flow = -flow
        events.append({"date": t["date"], "owner": t["owner"], "flow": flow})
    if not events:
        return pd.DataFrame()
    df = pd.DataFrame(events)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date")
    out = []
    for owner in df["owner"].unique():
        sub = df[df["owner"] == owner].copy()
        sub["cumulative"] = sub["flow"].cumsum()
        out.append(sub)
    return pd.concat(out)


# ─────────────────────────────────────────
# US Tax calculator
# ─────────────────────────────────────────

MFJ_ORDINARY_BRACKETS_2025 = [
    (23850,   0.10),
    (96950,   0.12),
    (206700,  0.22),
    (394600,  0.24),
    (501050,  0.32),
    (751600,  0.35),
    (float("inf"), 0.37),
]


def bracket_tax(taxable: float, brackets=MFJ_ORDINARY_BRACKETS_2025) -> float:
    tax = 0.0
    prev = 0.0
    for limit, rate in brackets:
        if taxable <= prev:
            break
        tax += (min(taxable, limit) - prev) * rate
        prev = limit
    return tax


def compute_us_tax(
    lt_gains_krw: float,
    st_gains_krw: float,
    earned_kim_usd: float,
    earned_yoon_usd: float,
    feie_kim_usd: float,
    feie_yoon_usd: float,
    exchange_rate: float,
    other_income_usd: float = 0.0,
    std_deduction: float = 30200.0,
    lt_0pct_limit: float = 96700.0,   # MFJ 2025 (use as 2026 proxy)
    lt_15pct_limit: float = 583750.0,
    niit_threshold: float = 250000.0,
) -> dict:
    lt = lt_gains_krw / exchange_rate
    st = st_gains_krw / exchange_rate

    # Net earned income after FEIE
    net_earned = max(0.0, (earned_kim_usd - feie_kim_usd) + (earned_yoon_usd - feie_yoon_usd))

    # Ordinary income = net earned + other income + ST gains
    ordinary_income = net_earned + other_income_usd + st

    # Standard deduction reduces ordinary income first, then spills into LT
    ordinary_taxable = max(0.0, ordinary_income - std_deduction)
    leftover_deduction = max(0.0, std_deduction - ordinary_income)
    lt_taxable = max(0.0, lt - leftover_deduction)

    # LT gains sit on top of ordinary income for bracket determination
    income_floor = ordinary_taxable  # LT gains start here
    lt_in_0pct  = max(0.0, min(lt_taxable, max(0.0, lt_0pct_limit  - income_floor)))
    lt_in_15pct = max(0.0, min(lt_taxable - lt_in_0pct,
                                max(0.0, lt_15pct_limit - lt_0pct_limit - max(0.0, income_floor - lt_0pct_limit))))
    lt_in_20pct = max(0.0, lt_taxable - lt_in_0pct - lt_in_15pct)

    lt_tax = lt_in_15pct * 0.15 + lt_in_20pct * 0.20
    ordinary_tax = bracket_tax(ordinary_taxable)

    # NIIT 3.8% on net investment income if MAGI > threshold
    magi = net_earned + other_income_usd + lt + st
    niit = 0.0
    if magi > niit_threshold:
        net_invest = lt + st
        niit = min(net_invest, magi - niit_threshold) * 0.038

    total_tax = ordinary_tax + lt_tax + niit

    # Margin: how much more LT gains before leaving 0% bracket
    margin_0pct = max(0.0, lt_0pct_limit - income_floor - lt_taxable)

    return {
        "lt_krw": lt_gains_krw,
        "st_krw": st_gains_krw,
        "lt_usd": lt,
        "st_usd": st,
        "net_earned_usd": net_earned,
        "ordinary_income": ordinary_income,
        "ordinary_taxable": ordinary_taxable,
        "lt_taxable": lt_taxable,
        "lt_in_0pct": lt_in_0pct,
        "lt_in_15pct": lt_in_15pct,
        "lt_in_20pct": lt_in_20pct,
        "lt_tax": lt_tax,
        "ordinary_tax": ordinary_tax,
        "niit": niit,
        "total_tax": total_tax,
        "margin_to_0pct": margin_0pct,
        "magi": magi,
    }


# ─────────────────────────────────────────
# UI
# ─────────────────────────────────────────

with st.sidebar:
    st.markdown("#### 📈 포트폴리오 트래커")
    owner_sel = st.radio("소유자", ["전체", "윤선화", "김희돈"], label_visibility="collapsed")
    st.caption(f"마지막 거래: {max(t['date'] for t in TRANSACTIONS if t['type'] in ('buy','sell'))}")

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["💼 현재 보유", "📊 손익 분석", "📅 시점별 조회", "📋 거래 내역", "🇺🇸 세금 계산"]
)


# ─── Tab 1: 현재 보유 ───────────────────
with tab1:
    st.subheader("현재 보유 종목")
    owners_to_show = ["윤선화", "김희돈"] if owner_sel == "전체" else [owner_sel]

    for owner in owners_to_show:
        positions = CURRENT_POSITIONS[owner]
        if not positions:
            continue

        rows = []
        total_cost = total_eval = 0
        for pos in positions:
            rt = fetch_realtime(pos["code"])
            cur_price = rt["price"] if rt else None
            cost = pos["avg_price"] * pos["shares"]
            eval_val = cur_price * pos["shares"] if cur_price else None
            gain = (eval_val - cost) if eval_val is not None else None
            pct = (gain / cost * 100) if gain is not None and cost else None
            total_cost += cost
            if eval_val:
                total_eval += eval_val
            rows.append({
                "종목": pos["name"],
                "보유주": f"{pos['shares']:,}",
                "평균매입가": fmt_krw(pos["avg_price"]),
                "매입금액": fmt_krw(cost),
                "현재가": fmt_krw(cur_price) if cur_price else "조회 중",
                "평가금액": fmt_krw(eval_val) if eval_val else "-",
                "손익": fmt_krw(gain) if gain is not None else "-",
                "수익률": fmt_pct(pct) if pct is not None else "-",
            })

        total_gain = total_eval - total_cost if total_eval else None
        total_pct = (total_gain / total_cost * 100) if total_gain and total_cost else None

        with st.expander(f"**{owner}**  총매입 {fmt_krw(total_cost)}  |  평가 {fmt_krw(total_eval) if total_eval else '-'}  |  손익 {fmt_krw(total_gain) if total_gain else '-'}  ({fmt_pct(total_pct) if total_pct else '-'})", expanded=True):
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True, hide_index=True)


# ─── Tab 2: 손익 분석 ───────────────────
with tab2:
    st.subheader("손익 분석")
    owner_f2 = None if owner_sel == "전체" else owner_sel

    # ── 실현 손익 테이블
    st.markdown("#### 실현 손익 (FIFO)")
    realized = compute_realized_gains(owner_filter=owner_f2)
    if realized:
        # Aggregate by (owner, name, year)
        agg = defaultdict(lambda: {"cost": 0, "proceeds": 0, "gain": 0, "lt_gain": 0, "st_gain": 0})
        for r in realized:
            k = (r["owner"], r["name"], r["year"])
            agg[k]["cost"] += r["cost"]
            agg[k]["proceeds"] += r["proceeds"]
            agg[k]["gain"] += r["gain"]
            if r["is_lt"]:
                agg[k]["lt_gain"] += r["gain"]
            else:
                agg[k]["st_gain"] += r["gain"]

        agg_rows = []
        for (owner, name, yr), v in sorted(agg.items()):
            agg_rows.append({
                "연도": yr,
                "소유자": owner,
                "종목": name,
                "매입원가": fmt_krw(v["cost"]),
                "매도금액": fmt_krw(v["proceeds"]),
                "실현손익": fmt_krw(v["gain"]),
                "장기(LT)": fmt_krw(v["lt_gain"]),
                "단기(ST)": fmt_krw(v["st_gain"]),
            })
        df_realized = pd.DataFrame(agg_rows)
        if owner_sel != "전체":
            df_realized = df_realized.drop(columns=["소유자"])
        st.dataframe(df_realized, use_container_width=True, hide_index=True)

        total_gain_all = sum(r["gain"] for r in realized)
        total_lt = sum(r["gain"] for r in realized if r["is_lt"])
        total_st = sum(r["gain"] for r in realized if not r["is_lt"])
        c1, c2, c3 = st.columns(3)
        c1.metric("총 실현손익", fmt_krw(total_gain_all))
        c2.metric("장기(LT)", fmt_krw(total_lt))
        c3.metric("단기(ST)", fmt_krw(total_st))
    else:
        st.info("해당 소유자의 실현 손익 데이터가 없습니다.")

    st.divider()

    # ── 누적 투자금 차트
    st.markdown("#### 누적 투자금 흐름")
    cf = cumulative_cashflow()
    if not cf.empty:
        if owner_sel != "전체":
            cf = cf[cf["owner"] == owner_sel]
        fig = go.Figure()
        colors = {"윤선화": "#4C9BE8", "김희돈": "#F4845F"}
        for owner in cf["owner"].unique():
            sub = cf[cf["owner"] == owner].sort_values("date")
            fig.add_trace(go.Scatter(
                x=sub["date"], y=sub["cumulative"],
                mode="lines", name=owner,
                line=dict(color=colors.get(owner, "#888"), width=2),
            ))
        fig.update_layout(
            yaxis_title="누적 순투자금 (원)",
            xaxis_title="",
            legend=dict(orientation="h", y=1.1),
            height=350,
            margin=dict(l=0, r=0, t=20, b=0),
        )
        fig.update_yaxes(tickformat=",")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("누적 순투자금 = 누적 매수금액 - 누적 매도금액")


# ─── Tab 3: 시점별 조회 ─────────────────
with tab3:
    st.subheader("시점별 보유현황 조회")
    query_date = st.date_input("조회 날짜", value=date.today(), min_value=date(2020, 1, 1), max_value=date.today())
    owner_f3 = None if owner_sel == "전체" else owner_sel

    holdings = compute_holdings_at(query_date.strftime("%Y-%m-%d"), owner_filter=owner_f3)

    if holdings:
        rows3 = []
        for h in sorted(holdings, key=lambda x: (x["owner"], x["name"])):
            rows3.append({
                "소유자": h["owner"],
                "종목": h["name"],
                "종목코드": h["code"],
                "보유주": f"{h['shares']:.0f}",
                "평균매입가": fmt_krw(h["avg_price"]),
                "매입금액": fmt_krw(h["total_cost"]),
            })
        df3 = pd.DataFrame(rows3)
        if owner_sel != "전체":
            df3 = df3.drop(columns=["소유자"])
        st.dataframe(df3, use_container_width=True, hide_index=True)

        total_invested = sum(h["total_cost"] for h in holdings)
        st.metric("총 투자금 (해당 시점)", fmt_krw(total_invested))
    else:
        st.info(f"{query_date} 기준 보유 종목 없음")


# ─── Tab 4: 거래 내역 ───────────────────
with tab4:
    st.subheader("전체 거래 내역")

    txns = [t for t in TRANSACTIONS if t["type"] in ("buy", "sell")]
    if owner_sel != "전체":
        txns = [t for t in txns if t["owner"] == owner_sel]

    col_a, col_b = st.columns(2)
    with col_a:
        type_filter = st.multiselect("거래유형", ["buy", "sell"], default=["buy", "sell"], format_func=lambda x: "매수" if x == "buy" else "매도")
    with col_b:
        stocks_in = sorted(set(t["name"] for t in txns))
        stock_filter = st.multiselect("종목 필터", stocks_in, default=stocks_in)

    txns = [t for t in txns if t["type"] in type_filter and t["name"] in stock_filter]
    txns_sorted = sorted(txns, key=lambda x: x["date"], reverse=True)

    rows4 = []
    for t in txns_sorted:
        amount = t["price"] * t["shares"]
        rows4.append({
            "날짜": t["date"],
            "소유자": t["owner"],
            "종목": t["name"],
            "구분": "매수" if t["type"] == "buy" else "매도",
            "단가": fmt_krw(t["price"]),
            "수량": f"{int(t['shares']):,}",
            "금액": fmt_krw(amount),
            "비고": t.get("note", ""),
        })

    df4 = pd.DataFrame(rows4)
    if owner_sel != "전체":
        df4 = df4.drop(columns=["소유자"])
    st.dataframe(df4, use_container_width=True, hide_index=True)
    st.caption(f"총 {len(rows4)}건")


# ─── Tab 5: 세금 계산 ───────────────────
with tab5:
    st.subheader("🇺🇸 미국 세금 계산기 (MFJ · FEIE)")
    st.caption("2026 과세연도 기준 (2027년 신고) | 세율은 2025년 확정 브래킷 준용")

    with st.expander("⚙️ 세금 계산 파라미터 (클릭하여 수정)", expanded=False):
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            std_deduction = st.number_input("표준공제 (MFJ, USD)", value=30200, step=100)
            lt_0pct = st.number_input("LT 0% 상한선 (MFJ taxable income, USD)", value=96700, step=1000)
            lt_15pct = st.number_input("LT 15% 상한선 (USD)", value=583750, step=1000)
        with col_p2:
            niit_thresh = st.number_input("NIIT 기준 MAGI (MFJ, USD)", value=250000, step=1000)
            feie_limit_each = st.number_input("FEIE 1인 한도 (USD)", value=133000, step=1000)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**환율 및 세금연도**")
        exchange_rate = st.number_input("적용 환율 (₩/USD)", value=1380, min_value=500, max_value=2000, step=10)
        tax_year = st.number_input("세금연도", value=2026, min_value=2020, max_value=2030)

    with col2:
        st.markdown("**실현 손익 조회 범위**")
        owner_tax = st.radio("소유자", ["전체", "윤선화", "김희돈"], key="tax_owner", horizontal=True)

    st.divider()
    st.markdown("**근로소득 및 FEIE 입력 (USD)**")
    col_e1, col_e2 = st.columns(2)
    with col_e1:
        st.markdown("*김희돈*")
        earned_kim = st.number_input("근로소득", value=0, min_value=0, step=1000, key="e_kim")
        feie_kim   = st.number_input(f"FEIE 제외금액 (최대 {feie_limit_each:,})", value=min(earned_kim, feie_limit_each), min_value=0, max_value=feie_limit_each, step=1000, key="f_kim")
    with col_e2:
        st.markdown("*윤선화*")
        earned_yoon = st.number_input("근로소득", value=0, min_value=0, step=1000, key="e_yoon")
        feie_yoon   = st.number_input(f"FEIE 제외금액 (최대 {feie_limit_each:,})", value=min(earned_yoon, feie_limit_each), min_value=0, max_value=feie_limit_each, step=1000, key="f_yoon")

    other_income = st.number_input("기타 소득 (USD, 배당·이자 등)", value=0, min_value=0, step=100)

    st.divider()

    # 해당 연도 실현 손익 계산
    owner_f5 = None if owner_tax == "전체" else owner_tax
    realized5 = compute_realized_gains(owner_filter=owner_f5, year_filter=int(tax_year))

    lt_gains_krw = sum(r["gain"] for r in realized5 if r["is_lt"])
    st_gains_krw = sum(r["gain"] for r in realized5 if not r["is_lt"])

    st.markdown(f"**{int(tax_year)}년 실현 손익 요약** ({owner_tax})")
    col_r1, col_r2, col_r3 = st.columns(3)
    col_r1.metric("LT 실현손익 (원)", fmt_krw(lt_gains_krw))
    col_r2.metric("ST 실현손익 (원)", fmt_krw(st_gains_krw))
    col_r3.metric("합계 (원)", fmt_krw(lt_gains_krw + st_gains_krw))

    # 세부 내역
    if realized5:
        with st.expander("실현 손익 상세 내역"):
            rows5 = []
            for r in sorted(realized5, key=lambda x: x["sell_date"]):
                rows5.append({
                    "매도일": r["sell_date"],
                    "소유자": r["owner"],
                    "종목": r["name"],
                    "구분": "LT(장기)" if r["is_lt"] else "ST(단기)",
                    "보유일": r["holding_days"],
                    "매입단가": fmt_krw(r["cost_per_share"]),
                    "매도단가": fmt_krw(r["sell_per_share"]),
                    "수량": f"{r['shares']:.0f}",
                    "손익(원)": fmt_krw(r["gain"]),
                })
            st.dataframe(pd.DataFrame(rows5), use_container_width=True, hide_index=True)

    st.divider()
    st.markdown("**계산 결과**")

    result = compute_us_tax(
        lt_gains_krw=lt_gains_krw,
        st_gains_krw=st_gains_krw,
        earned_kim_usd=float(earned_kim),
        earned_yoon_usd=float(earned_yoon),
        feie_kim_usd=float(feie_kim),
        feie_yoon_usd=float(feie_yoon),
        exchange_rate=float(exchange_rate),
        other_income_usd=float(other_income),
        std_deduction=float(std_deduction),
        lt_0pct_limit=float(lt_0pct),
        lt_15pct_limit=float(lt_15pct),
        niit_threshold=float(niit_thresh),
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("LT 손익 (USD)", fmt_usd(result["lt_usd"]))
    c2.metric("ST 손익 (USD)", fmt_usd(result["st_usd"]))
    c3.metric("순근로소득 (FEIE후)", fmt_usd(result["net_earned_usd"]))
    c4.metric("MAGI", fmt_usd(result["magi"]))

    st.markdown("")
    c5, c6, c7 = st.columns(3)
    c5.metric("LT 과세 손익 (USD)", fmt_usd(result["lt_taxable"]),
              help="표준공제 적용 후 LT 과세 대상")
    c6.metric("0% 적용 LT", fmt_usd(result["lt_in_0pct"]))
    c7.metric("15% 적용 LT", fmt_usd(result["lt_in_15pct"]))

    st.markdown("")
    c8, c9, c10, c11 = st.columns(4)
    c8.metric("LT 세금", fmt_usd(result["lt_tax"]))
    c9.metric("일반소득세 (ST 포함)", fmt_usd(result["ordinary_tax"]))
    c10.metric("NIIT (3.8%)", fmt_usd(result["niit"]))
    c11.metric("**총 세금 합계**", fmt_usd(result["total_tax"]))

    margin = result["margin_to_0pct"]
    if margin > 0:
        st.success(f"✅ **LT 0% 세율까지 여유: {fmt_usd(margin)}** (≈ {fmt_krw(margin * exchange_rate)})")
    else:
        over = -margin
        st.warning(f"⚠️ LT 0% 구간 초과: {fmt_usd(over)} 이미 15% 구간")

    with st.expander("📋 계산 근거"):
        st.markdown(f"""
| 항목 | 금액 |
|------|------|
| LT 실현손익 (원) | {fmt_krw(result['lt_krw'])} |
| ST 실현손익 (원) | {fmt_krw(result['st_krw'])} |
| 적용 환율 | ₩{exchange_rate:,}/USD |
| LT 실현손익 (USD) | {fmt_usd(result['lt_usd'])} |
| ST 실현손익 (USD) | {fmt_usd(result['st_usd'])} |
| 순근로소득 (FEIE 제외 후) | {fmt_usd(result['net_earned_usd'])} |
| 기타소득 | {fmt_usd(other_income)} |
| 일반소득 합계 (ST+근로+기타) | {fmt_usd(result['ordinary_income'])} |
| 표준공제 | {fmt_usd(std_deduction)} |
| 일반 과세소득 | {fmt_usd(result['ordinary_taxable'])} |
| LT 과세소득 (표준공제 잔여 적용 후) | {fmt_usd(result['lt_taxable'])} |
| LT @ 0% | {fmt_usd(result['lt_in_0pct'])} |
| LT @ 15% | {fmt_usd(result['lt_in_15pct'])} |
| LT @ 20% | {fmt_usd(result['lt_in_20pct'])} |
| LT 세금 | {fmt_usd(result['lt_tax'])} |
| 일반소득세 | {fmt_usd(result['ordinary_tax'])} |
| NIIT (3.8%) | {fmt_usd(result['niit'])} |
| **총 세금** | **{fmt_usd(result['total_tax'])}** |

> ⚠️ 본 계산기는 참고용입니다. 실제 신고 전 세무사 확인을 권장합니다.
> LT/ST 분류: 미국 세법 기준 보유기간 365일 이상 = LT
> 한국 증권거래세 및 외국납부세액공제는 별도 검토 필요
        """)
