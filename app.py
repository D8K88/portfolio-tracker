import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import date, timedelta, datetime
from collections import defaultdict

from transactions import STOCK_INFO

st.set_page_config(page_title="포트폴리오 트래커", page_icon="📈", layout="wide")

# ─────────────────────────────────────────
# 비밀번호 게이트
# ─────────────────────────────────────────
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.markdown("#### 🔒 포트폴리오 트래커")
    pwd = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
    if st.button("로그인", use_container_width=True):
        if pwd == st.secrets.get("app", {}).get("password", ""):
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

# ─────────────────────────────────────────
# 데이터 로드 (Secrets에서)
# ─────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_data():
    txns = json.loads(st.secrets["data"]["transactions"])
    pos  = json.loads(st.secrets["data"]["current_positions"])
    return txns, pos

TRANSACTIONS, CURRENT_POSITIONS = _load_data()

# ─────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────
def fmt_krw(v):
    if v is None:
        return "-"
    return f"₩{int(v):,}"

def fmt_pct(v):
    if v is None:
        return "-"
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
            over_price = d.get("overMarketPriceInfo", {}).get("overPrice", "")
            close_raw  = d.get("closePriceRaw", 0)
            if over_price and str(over_price).replace(",", "").isdigit():
                price = int(str(over_price).replace(",", ""))
            else:
                price = int(close_raw) if close_raw else 0
            return {"price": price, "close": int(close_raw)}
    except Exception:
        pass
    return None


def apply_fifo(lots: list, sell_shares: float):
    remaining = sell_shares
    new_lots  = []
    for lot in lots:
        if remaining <= 0:
            new_lots.append(lot)
            continue
        take = min(lot["shares"], remaining)
        if lot["shares"] - take > 1e-6:
            new_lots.append({**lot, "shares": lot["shares"] - take})
        remaining -= take
    return new_lots


def compute_realized_gains(owner_filter=None, year_filter=None) -> list:
    realized   = []
    lots_state = {}

    for t in sorted(TRANSACTIONS, key=lambda x: x["date"]):
        key = (t["owner"], t["code"])
        if key not in lots_state:
            lots_state[key] = []

        if t["type"] == "buy":
            lots_state[key].append({
                "date": t["date"],
                "shares": float(t["shares"]),
                "price": float(t["price"]),
            })

        elif t["type"] == "sell":
            if owner_filter and t["owner"] != owner_filter:
                # still need to update lots for unfiltered owners
                lots_state[key] = apply_fifo(lots_state[key], float(t["shares"]))
                continue
            sell_date  = t["date"]
            sell_price = float(t["price"])
            remaining  = float(t["shares"])

            for lot in lots_state[key]:
                if remaining <= 1e-6:
                    break
                take    = min(lot["shares"], remaining)
                buy_dt  = datetime.strptime(lot["date"], "%Y-%m-%d").date()
                sell_dt = datetime.strptime(sell_date, "%Y-%m-%d").date()
                days    = (sell_dt - buy_dt).days
                realized.append({
                    "owner":         t["owner"],
                    "code":          t["code"],
                    "name":          t["name"],
                    "buy_date":      lot["date"],
                    "sell_date":     sell_date,
                    "shares":        take,
                    "cost_per_share":lot["price"],
                    "sell_per_share":sell_price,
                    "cost":          lot["price"] * take,
                    "proceeds":      sell_price * take,
                    "gain":          (sell_price - lot["price"]) * take,
                    "holding_days":  days,
                    "is_lt":         days >= 365,
                    "year":          int(sell_date[:4]),
                })
                remaining -= take

            lots_state[key] = apply_fifo(lots_state[key], float(t["shares"]))

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
    lots_state = {}
    name_map   = {}

    for t in sorted(TRANSACTIONS, key=lambda x: x["date"]):
        if t["date"] > date_str:
            break
        key = (t["owner"], t["code"])
        name_map[key] = t["name"]
        if key not in lots_state:
            lots_state[key] = []

        if t["type"] == "buy":
            lots_state[key].append({
                "date": t["date"], "shares": float(t["shares"]), "price": float(t["price"])
            })
        elif t["type"] == "sell":
            lots_state[key] = apply_fifo(lots_state[key], float(t["shares"]))
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
            "owner": owner, "code": code,
            "name": name_map.get((owner, code), code),
            "shares": total_shares,
            "avg_price": total_cost / total_shares,
            "total_cost": total_cost,
        })
    return rows


def cumulative_cashflow() -> pd.DataFrame:
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
    parts = []
    for owner in df["owner"].unique():
        sub = df[df["owner"] == owner].copy()
        sub["cumulative"] = sub["flow"].cumsum()
        parts.append(sub)
    return pd.concat(parts)


# ─────────────────────────────────────────
# 미국 세금 계산
# ─────────────────────────────────────────
MFJ_BRACKETS_2025 = [
    (23850,       0.10),
    (96950,       0.12),
    (206700,      0.22),
    (394600,      0.24),
    (501050,      0.32),
    (751600,      0.35),
    (float("inf"),0.37),
]

def bracket_tax(taxable: float) -> float:
    tax, prev = 0.0, 0.0
    for limit, rate in MFJ_BRACKETS_2025:
        if taxable <= prev:
            break
        tax  += (min(taxable, limit) - prev) * rate
        prev  = limit
    return tax


def compute_us_tax(lt_krw, st_krw, earned_kim, earned_yoon,
                   feie_kim, feie_yoon, exchange_rate,
                   other_income=0.0, std_ded=30200.0,
                   lt_0pct=96700.0, lt_15pct=583750.0, niit_thr=250000.0):
    lt = lt_krw / exchange_rate
    st = st_krw / exchange_rate
    net_earned       = max(0.0, (earned_kim - feie_kim) + (earned_yoon - feie_yoon))
    ordinary_income  = net_earned + other_income + st
    ordinary_taxable = max(0.0, ordinary_income - std_ded)
    leftover_ded     = max(0.0, std_ded - ordinary_income)
    lt_taxable       = max(0.0, lt - leftover_ded)
    floor            = ordinary_taxable

    lt_0   = max(0.0, min(lt_taxable, max(0.0, lt_0pct  - floor)))
    lt_15  = max(0.0, min(lt_taxable - lt_0,
                           max(0.0, lt_15pct - lt_0pct - max(0.0, floor - lt_0pct))))
    lt_20  = max(0.0, lt_taxable - lt_0 - lt_15)
    lt_tax = lt_15 * 0.15 + lt_20 * 0.20
    ord_tax = bracket_tax(ordinary_taxable)

    magi = net_earned + other_income + lt + st
    niit = min(lt + st, max(0.0, magi - niit_thr)) * 0.038 if magi > niit_thr else 0.0
    margin = max(0.0, lt_0pct - floor - lt_taxable)

    return dict(lt_usd=lt, st_usd=st, net_earned=net_earned,
                ordinary_taxable=ordinary_taxable, lt_taxable=lt_taxable,
                lt_0=lt_0, lt_15=lt_15, lt_20=lt_20,
                lt_tax=lt_tax, ord_tax=ord_tax, niit=niit,
                total=lt_tax + ord_tax + niit, margin_0pct=margin, magi=magi)


# ─────────────────────────────────────────
# UI
# ─────────────────────────────────────────
with st.sidebar:
    st.markdown("#### 📈 포트폴리오 트래커")
    owner_sel = st.radio("소유자", ["전체", "윤선화", "김희돈"], label_visibility="collapsed")
    last_date = max(t["date"] for t in TRANSACTIONS if t["type"] in ("buy", "sell"))
    st.caption(f"마지막 거래: {last_date}")
    st.divider()
    if st.button("로그아웃", use_container_width=True):
        st.session_state.auth = False
        st.rerun()

tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["💼 현재 보유", "📊 손익 분석", "📅 시점별 조회", "📋 거래 내역", "🇺🇸 세금 계산"]
)


# ── Tab 1: 현재 보유 ─────────────────────
with tab1:
    st.subheader("현재 보유 종목")
    owners_show = ["윤선화", "김희돈"] if owner_sel == "전체" else [owner_sel]

    for owner in owners_show:
        positions = CURRENT_POSITIONS.get(owner, [])
        rows, total_cost, total_eval = [], 0, 0
        for pos in positions:
            rt    = fetch_realtime(pos["code"])
            cur   = rt["price"] if rt else None
            cost  = pos["avg_price"] * pos["shares"]
            ev    = cur * pos["shares"] if cur else None
            gain  = (ev - cost) if ev is not None else None
            pct   = (gain / cost * 100) if gain is not None and cost else None
            total_cost += cost
            if ev:
                total_eval += ev
            rows.append({
                "종목":     pos["name"],
                "보유주":   f"{pos['shares']:,}",
                "평균매입가": fmt_krw(pos["avg_price"]),
                "매입금액":  fmt_krw(cost),
                "현재가":   fmt_krw(cur) if cur else "조회 중",
                "평가금액":  fmt_krw(ev),
                "손익":     fmt_krw(gain),
                "수익률":   fmt_pct(pct),
            })

        total_gain = total_eval - total_cost if total_eval else None
        total_pct  = (total_gain / total_cost * 100) if total_gain and total_cost else None
        label = (f"**{owner}**  매입 {fmt_krw(total_cost)}  |  "
                 f"평가 {fmt_krw(total_eval) if total_eval else '-'}  |  "
                 f"손익 {fmt_krw(total_gain)}  ({fmt_pct(total_pct)})")
        with st.expander(label, expanded=True):
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Tab 2: 손익 분석 ─────────────────────
with tab2:
    st.subheader("손익 분석")
    owner_f = None if owner_sel == "전체" else owner_sel

    # 실현 손익
    st.markdown("#### 실현 손익 (FIFO 기준)")
    realized = compute_realized_gains(owner_filter=owner_f)
    if realized:
        agg = defaultdict(lambda: {"cost": 0, "proceeds": 0, "gain": 0, "lt": 0, "st": 0})
        for r in realized:
            k = (r["owner"], r["name"], r["year"])
            agg[k]["cost"]     += r["cost"]
            agg[k]["proceeds"] += r["proceeds"]
            agg[k]["gain"]     += r["gain"]
            if r["is_lt"]:
                agg[k]["lt"] += r["gain"]
            else:
                agg[k]["st"] += r["gain"]

        rows_r = []
        for (owner, name, yr), v in sorted(agg.items()):
            rows_r.append({"연도": yr, "소유자": owner, "종목": name,
                           "매입원가": fmt_krw(v["cost"]), "매도금액": fmt_krw(v["proceeds"]),
                           "실현손익": fmt_krw(v["gain"]),
                           "장기LT": fmt_krw(v["lt"]), "단기ST": fmt_krw(v["st"])})
        df_r = pd.DataFrame(rows_r)
        if owner_sel != "전체":
            df_r = df_r.drop(columns=["소유자"])
        st.dataframe(df_r, use_container_width=True, hide_index=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("총 실현손익", fmt_krw(sum(r["gain"] for r in realized)))
        c2.metric("장기(LT)", fmt_krw(sum(r["gain"] for r in realized if r["is_lt"])))
        c3.metric("단기(ST)", fmt_krw(sum(r["gain"] for r in realized if not r["is_lt"])))
    else:
        st.info("실현 손익 데이터 없음")

    st.divider()

    # 누적 투자금 차트
    st.markdown("#### 누적 순투자금 흐름")
    cf = cumulative_cashflow()
    if not cf.empty:
        if owner_sel != "전체":
            cf = cf[cf["owner"] == owner_sel]
        fig = go.Figure()
        colors = {"윤선화": "#4C9BE8", "김희돈": "#F4845F"}
        for o in cf["owner"].unique():
            sub = cf[cf["owner"] == o].sort_values("date")
            fig.add_trace(go.Scatter(x=sub["date"], y=sub["cumulative"],
                                     mode="lines", name=o,
                                     line=dict(color=colors.get(o, "#888"), width=2)))
        fig.update_layout(yaxis_title="누적 순투자금 (원)", xaxis_title="",
                          legend=dict(orientation="h", y=1.1),
                          height=350, margin=dict(l=0, r=0, t=20, b=0))
        fig.update_yaxes(tickformat=",")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("누적 순투자금 = 누적 매수금액 − 누적 매도금액")


# ── Tab 3: 시점별 조회 ───────────────────
with tab3:
    st.subheader("시점별 보유현황 조회")
    query_date = st.date_input("조회 날짜", value=date.today(),
                               min_value=date(2020, 1, 1), max_value=date.today())
    owner_f3 = None if owner_sel == "전체" else owner_sel
    holdings = compute_holdings_at(query_date.strftime("%Y-%m-%d"), owner_filter=owner_f3)

    if holdings:
        rows3 = []
        for h in sorted(holdings, key=lambda x: (x["owner"], x["name"])):
            rows3.append({"소유자": h["owner"], "종목": h["name"], "코드": h["code"],
                          "보유주": f"{h['shares']:.0f}",
                          "평균매입가": fmt_krw(h["avg_price"]),
                          "매입금액": fmt_krw(h["total_cost"])})
        df3 = pd.DataFrame(rows3)
        if owner_sel != "전체":
            df3 = df3.drop(columns=["소유자"])
        st.dataframe(df3, use_container_width=True, hide_index=True)
        st.metric("총 투자금 (해당 시점)", fmt_krw(sum(h["total_cost"] for h in holdings)))
    else:
        st.info(f"{query_date} 기준 보유 종목 없음")


# ── Tab 4: 거래 내역 ─────────────────────
with tab4:
    st.subheader("전체 거래 내역")
    txns = [t for t in TRANSACTIONS if t["type"] in ("buy", "sell")]
    if owner_sel != "전체":
        txns = [t for t in txns if t["owner"] == owner_sel]

    col_a, col_b = st.columns(2)
    with col_a:
        type_f = st.multiselect("거래유형", ["buy", "sell"], default=["buy", "sell"],
                                format_func=lambda x: "매수" if x == "buy" else "매도")
    with col_b:
        stocks_in = sorted(set(t["name"] for t in txns))
        stock_f   = st.multiselect("종목 필터", stocks_in, default=stocks_in)

    txns = [t for t in txns if t["type"] in type_f and t["name"] in stock_f]
    rows4 = []
    for t in sorted(txns, key=lambda x: x["date"], reverse=True):
        rows4.append({"날짜": t["date"], "소유자": t["owner"], "종목": t["name"],
                      "구분": "매수" if t["type"] == "buy" else "매도",
                      "단가": fmt_krw(t["price"]), "수량": f"{int(t['shares']):,}",
                      "금액": fmt_krw(t["price"] * t["shares"]),
                      "비고": t.get("note", "")})
    df4 = pd.DataFrame(rows4)
    if owner_sel != "전체":
        df4 = df4.drop(columns=["소유자"])
    st.dataframe(df4, use_container_width=True, hide_index=True)
    st.caption(f"총 {len(rows4)}건")


# ── Tab 5: 세금 계산 ─────────────────────
with tab5:
    st.subheader("🇺🇸 미국 세금 계산기 (MFJ · FEIE)")
    st.caption("2026 과세연도 기준 (2027년 신고) | 세율 브래킷은 2025년 확정치 준용")

    with st.expander("⚙️ 세율 파라미터", expanded=False):
        p1, p2 = st.columns(2)
        with p1:
            std_ded   = st.number_input("표준공제 (MFJ, USD)", value=30200, step=100)
            lt_0pct   = st.number_input("LT 0% 상한 (과세소득, USD)", value=96700, step=1000)
            lt_15pct  = st.number_input("LT 15% 상한 (과세소득, USD)", value=583750, step=1000)
        with p2:
            niit_thr  = st.number_input("NIIT 기준 MAGI (MFJ, USD)", value=250000, step=1000)
            feie_cap  = st.number_input("FEIE 1인 한도 (USD)", value=133000, step=1000)

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        xrate    = st.number_input("적용 환율 (₩/USD)", value=1380, min_value=500, max_value=2000, step=10)
        tax_year = st.number_input("세금연도", value=2026, min_value=2020, max_value=2030)
    with c2:
        owner_tax = st.radio("실현손익 소유자", ["전체", "윤선화", "김희돈"], key="tax_owner", horizontal=True)

    st.divider()
    st.markdown("**근로소득 및 FEIE 입력 (USD)**")
    e1, e2 = st.columns(2)
    with e1:
        st.markdown("*김희돈*")
        earn_kim = st.number_input("근로소득", value=0, min_value=0, step=1000, key="ek")
        feie_kim = st.number_input(f"FEIE 제외 (최대 {feie_cap:,})", value=min(earn_kim, feie_cap), min_value=0, max_value=feie_cap, step=1000, key="fk")
    with e2:
        st.markdown("*윤선화*")
        earn_yoon = st.number_input("근로소득", value=0, min_value=0, step=1000, key="ey")
        feie_yoon = st.number_input(f"FEIE 제외 (최대 {feie_cap:,})", value=min(earn_yoon, feie_cap), min_value=0, max_value=feie_cap, step=1000, key="fy")
    other_inc = st.number_input("기타 소득 (배당·이자, USD)", value=0, min_value=0, step=100)

    st.divider()
    owner_f5  = None if owner_tax == "전체" else owner_tax
    realized5 = compute_realized_gains(owner_filter=owner_f5, year_filter=int(tax_year))
    lt_krw = sum(r["gain"] for r in realized5 if r["is_lt"])
    st_krw = sum(r["gain"] for r in realized5 if not r["is_lt"])

    st.markdown(f"**{int(tax_year)}년 실현 손익 ({owner_tax})**")
    m1, m2, m3 = st.columns(3)
    m1.metric("LT 실현손익 (원)", fmt_krw(lt_krw))
    m2.metric("ST 실현손익 (원)", fmt_krw(st_krw))
    m3.metric("합계 (원)", fmt_krw(lt_krw + st_krw))

    if realized5:
        with st.expander("실현 손익 상세"):
            rows5 = [{"매도일": r["sell_date"], "소유자": r["owner"], "종목": r["name"],
                      "구분": "LT" if r["is_lt"] else "ST", "보유일": r["holding_days"],
                      "매입단가": fmt_krw(r["cost_per_share"]), "매도단가": fmt_krw(r["sell_per_share"]),
                      "수량": f"{r['shares']:.0f}", "손익(원)": fmt_krw(r["gain"])} for r in sorted(realized5, key=lambda x: x["sell_date"])]
            st.dataframe(pd.DataFrame(rows5), use_container_width=True, hide_index=True)

    st.divider()
    res = compute_us_tax(lt_krw, st_krw, float(earn_kim), float(earn_yoon),
                         float(feie_kim), float(feie_yoon), float(xrate),
                         float(other_inc), float(std_ded), float(lt_0pct),
                         float(lt_15pct), float(niit_thr))

    st.markdown("**계산 결과**")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("LT 손익 (USD)", fmt_usd(res["lt_usd"]))
    r2.metric("ST 손익 (USD)", fmt_usd(res["st_usd"]))
    r3.metric("순근로소득 (FEIE후)", fmt_usd(res["net_earned"]))
    r4.metric("MAGI", fmt_usd(res["magi"]))

    r5, r6, r7 = st.columns(3)
    r5.metric("LT 과세소득", fmt_usd(res["lt_taxable"]), help="표준공제 잔여 적용 후")
    r6.metric("0% 적용 LT", fmt_usd(res["lt_0"]))
    r7.metric("15% 적용 LT", fmt_usd(res["lt_15"]))

    r8, r9, r10, r11 = st.columns(4)
    r8.metric("LT 세금", fmt_usd(res["lt_tax"]))
    r9.metric("일반소득세 (ST포함)", fmt_usd(res["ord_tax"]))
    r10.metric("NIIT (3.8%)", fmt_usd(res["niit"]))
    r11.metric("**총 세금**", fmt_usd(res["total"]))

    margin = res["margin_0pct"]
    if margin > 0:
        st.success(f"✅ LT 0% 구간까지 여유: **{fmt_usd(margin)}** (≈ {fmt_krw(margin * xrate)})")
    else:
        st.warning(f"⚠️ LT 0% 구간 초과: {fmt_usd(-margin)} 이미 15% 구간 진입")

    with st.expander("📋 계산 근거"):
        st.markdown(f"""
| 항목 | 금액 |
|------|------|
| LT 실현손익 (원→USD) | {fmt_krw(lt_krw)} → {fmt_usd(res['lt_usd'])} |
| ST 실현손익 (원→USD) | {fmt_krw(st_krw)} → {fmt_usd(res['st_usd'])} |
| 적용 환율 | ₩{xrate:,}/USD |
| 순근로소득 (FEIE 제외 후) | {fmt_usd(res['net_earned'])} |
| 기타소득 | {fmt_usd(other_inc)} |
| 표준공제 (MFJ) | {fmt_usd(std_ded)} |
| 일반 과세소득 | {fmt_usd(res['ordinary_taxable'])} |
| LT 과세소득 | {fmt_usd(res['lt_taxable'])} |
| LT @ 0% | {fmt_usd(res['lt_0'])} |
| LT @ 15% | {fmt_usd(res['lt_15'])} |
| LT @ 20% | {fmt_usd(res['lt_20'])} |
| LT 세금 | {fmt_usd(res['lt_tax'])} |
| 일반소득세 | {fmt_usd(res['ord_tax'])} |
| NIIT (3.8%) | {fmt_usd(res['niit'])} |
| **총 세금** | **{fmt_usd(res['total'])}** |

> ⚠️ 참고용입니다. 실제 신고 전 세무사 확인 권장.
> LT 기준: 보유 365일 이상 | 한국 증권거래세·외국납부세액공제는 별도
        """)
