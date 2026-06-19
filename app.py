import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
from datetime import date, timedelta, datetime
from collections import defaultdict

from transactions import STOCK_INFO

st.set_page_config(page_title="포트폴리오 트래커", page_icon="💰", layout="wide")

# ─────────────────────────────────────────
# 비밀번호 게이트
# ─────────────────────────────────────────
if "auth" not in st.session_state:
    st.session_state.auth = False

if not st.session_state.auth:
    st.markdown("#### 🔐 Portfolio Tracker")
    pwd = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
    if st.button("로그인", use_container_width=True):
        if pwd == st.secrets.get("app", {}).get("password", ""):
            st.session_state.auth = True
            st.rerun()
        else:
            st.error("비밀번호가 올바르지 않습니다.")
    st.stop()

# ─────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_data():
    txns = json.loads(st.secrets["data"]["transactions"])
    pos  = json.loads(st.secrets["data"]["current_positions"])
    return txns, pos

_BASE_TXN, _BASE_POS = _load_data()

if "transactions" not in st.session_state:
    st.session_state.transactions = list(_BASE_TXN)
if "current_positions" not in st.session_state:
    st.session_state.current_positions = dict(_BASE_POS)

# ─────────────────────────────────────────
# Gist 기반 세금 설정 저장/로드
# ─────────────────────────────────────────
_TAX_DEFAULTS = dict(
    tx_xrate=1380, tx_year=2026,
    tx_std_ded=30200, tx_lt0=96700, tx_lt15=583750,
    tx_niit=250000, tx_feie_cap=133000,
    tx_earn_kim=0, tx_feie_kim=0,
    tx_earn_yoon=0, tx_feie_yoon=0, tx_other=0,
)
_TAX_GIST_FILE = "portfolio_tracker_tax.json"

def _gh_headers():
    token = st.secrets.get("github", {}).get("token", "")
    if not token:
        return None
    return {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

def _gist_id():
    return st.secrets.get("github", {}).get("gist_id", "")

def load_tax_settings() -> dict:
    gid, hdrs = _gist_id(), _gh_headers()
    if not gid or not hdrs:
        return {}
    try:
        r = requests.get(f"https://api.github.com/gists/{gid}", headers=hdrs, timeout=8)
        if r.status_code == 200:
            f = r.json().get("files", {}).get(_TAX_GIST_FILE)
            if f:
                return json.loads(f["content"])
    except Exception:
        pass
    return {}

def save_tax_settings() -> bool:
    gid, hdrs = _gist_id(), _gh_headers()
    if not gid or not hdrs:
        return False
    payload = {k: st.session_state[k] for k in _TAX_DEFAULTS}
    try:
        r = requests.patch(
            f"https://api.github.com/gists/{gid}",
            headers=hdrs,
            json={"files": {_TAX_GIST_FILE: {"content": json.dumps(payload, ensure_ascii=False)}}},
            timeout=8,
        )
        return r.status_code == 200
    except Exception:
        return False

# 세션 초기화: Gist에서 불러오거나 기본값 사용
if "tax_initialized" not in st.session_state:
    saved = load_tax_settings()
    for k, v in _TAX_DEFAULTS.items():
        st.session_state[k] = saved.get(k, v)
    st.session_state.tax_initialized = True

# ─────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────
def fmt_krw(v):
    if v is None: return "-"
    return f"₩{int(v):,}"

def fmt_pct(v):
    if v is None: return "-"
    return f"{'+'if v>=0 else''}{v:.2f}%"

def fmt_usd(v):
    return f"${v:,.0f}"


@st.cache_data(ttl=60, show_spinner=False)
def fetch_realtime(code: str):
    url = f"https://polling.finance.naver.com/api/realtime/domestic/stock/{code}"
    try:
        r = requests.get(url, timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            d = r.json().get("datas", [{}])[0]
            over  = d.get("overMarketPriceInfo", {}).get("overPrice", "")
            close = d.get("closePriceRaw", 0)
            price = int(str(over).replace(",","")) if str(over).replace(",","").isdigit() else int(close or 0)
            return {"price": price, "close": int(close or 0)}
    except Exception:
        pass
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_price_at_date(code: str, date_str: str):
    """pykrx로 특정 날짜 종가 조회 (최대 7영업일 이전까지 탐색)"""
    try:
        from pykrx import stock as krx
        d = datetime.strptime(date_str, "%Y-%m-%d")
        for i in range(8):
            check = d - timedelta(days=i)
            df = krx.get_market_ohlcv_by_date(check.strftime("%Y%m%d"), check.strftime("%Y%m%d"), code)
            if df is not None and not df.empty and "종가" in df.columns:
                return int(df["종가"].iloc[0])
    except Exception:
        pass
    return None


def apply_fifo(lots: list, sell_shares: float) -> list:
    remaining, new_lots = sell_shares, []
    for lot in lots:
        if remaining <= 0:
            new_lots.append(lot)
            continue
        take = min(lot["shares"], remaining)
        if lot["shares"] - take > 1e-6:
            new_lots.append({**lot, "shares": lot["shares"] - take})
        remaining -= take
    return new_lots


def compute_realized_gains(owner_filter=None, start_date=None, end_date=None) -> list:
    realized, lots_state = [], {}

    for t in sorted(st.session_state.transactions, key=lambda x: x["date"]):
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
                lots_state[key] = apply_fifo(lots_state[key], float(t["shares"]))
                continue

            sell_date, sell_price = t["date"], float(t["price"])
            remaining = float(t["shares"])

            for lot in lots_state[key]:
                if remaining <= 1e-6:
                    break
                take    = min(lot["shares"], remaining)
                buy_dt  = datetime.strptime(lot["date"], "%Y-%m-%d").date()
                sell_dt = datetime.strptime(sell_date, "%Y-%m-%d").date()
                days    = (sell_dt - buy_dt).days
                realized.append({
                    "owner":          t["owner"],
                    "code":           t["code"],
                    "name":           t["name"],
                    "buy_date":       lot["date"],
                    "sell_date":      sell_date,
                    "shares":         take,
                    "cost_per_share": lot["price"],
                    "sell_per_share": sell_price,
                    "cost":           lot["price"] * take,
                    "proceeds":       sell_price * take,
                    "gain":           (sell_price - lot["price"]) * take,
                    "holding_days":   days,
                    "is_lt":          days >= 365,
                    "year":           int(sell_date[:4]),
                })
                remaining -= take

            lots_state[key] = apply_fifo(lots_state[key], float(t["shares"]))

        elif t["type"] == "split":
            ratio = float(t["new_shares"]) / float(t["old_shares"])
            lots_state[key] = [
                {"date": l["date"], "shares": l["shares"] * ratio, "price": l["price"] / ratio}
                for l in lots_state[key]
            ]

    if start_date:
        realized = [r for r in realized if r["sell_date"] >= start_date]
    if end_date:
        realized = [r for r in realized if r["sell_date"] <= end_date]
    return realized


def compute_holdings_at(date_str: str, owner_filter=None) -> list:
    lots_state, name_map = {}, {}
    for t in sorted(st.session_state.transactions, key=lambda x: x["date"]):
        if t["date"] > date_str:
            break
        key = (t["owner"], t["code"])
        name_map[key] = t["name"]
        if key not in lots_state:
            lots_state[key] = []
        if t["type"] == "buy":
            lots_state[key].append({"date": t["date"], "shares": float(t["shares"]), "price": float(t["price"])})
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
        total = sum(l["shares"] for l in lots)
        if total < 0.01:
            continue
        total_cost = sum(l["shares"] * l["price"] for l in lots)
        rows.append({
            "owner": owner, "code": code,
            "name": name_map.get((owner, code), code),
            "shares": total, "avg_price": total_cost / total, "total_cost": total_cost,
        })
    return rows


def cumulative_cashflow() -> pd.DataFrame:
    events = []
    for t in st.session_state.transactions:
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
    for o in df["owner"].unique():
        sub = df[df["owner"] == o].copy()
        sub["cumulative"] = sub["flow"].cumsum()
        parts.append(sub)
    return pd.concat(parts)


# ─────────────────────────────────────────
# 미국 세금 계산
# ─────────────────────────────────────────
MFJ_BRACKETS = [
    (23850, .10), (96950, .12), (206700, .22), (394600, .24),
    (501050, .32), (751600, .35), (float("inf"), .37),
]

def bracket_tax(taxable: float) -> float:
    tax, prev = 0., 0.
    for lim, rate in MFJ_BRACKETS:
        if taxable <= prev: break
        tax  += (min(taxable, lim) - prev) * rate
        prev  = lim
    return tax

def compute_us_tax(lt_krw, st_krw, earn_kim, earn_yoon, feie_kim, feie_yoon,
                   xrate, other=0., std_ded=30200., lt0=96700., lt15=583750., niit_thr=250000.):
    lt  = lt_krw / xrate
    st_ = st_krw / xrate
    net_earned   = max(0., (earn_kim - feie_kim) + (earn_yoon - feie_yoon))
    ord_income   = net_earned + other + st_
    ord_taxable  = max(0., ord_income - std_ded)
    leftover     = max(0., std_ded - ord_income)
    lt_taxable   = max(0., lt - leftover)
    floor        = ord_taxable
    lt_0  = max(0., min(lt_taxable, max(0., lt0  - floor)))
    lt_15 = max(0., min(lt_taxable - lt_0, max(0., lt15 - lt0 - max(0., floor - lt0))))
    lt_20 = max(0., lt_taxable - lt_0 - lt_15)
    lt_tax  = lt_15 * .15 + lt_20 * .20
    ord_tax = bracket_tax(ord_taxable)
    magi    = net_earned + other + lt + st_
    niit    = min(lt + st_, max(0., magi - niit_thr)) * .038 if magi > niit_thr else 0.
    margin  = max(0., lt0 - floor - lt_taxable)
    return dict(lt_usd=lt, st_usd=st_, net_earned=net_earned,
                ord_taxable=ord_taxable, lt_taxable=lt_taxable,
                lt_0=lt_0, lt_15=lt_15, lt_20=lt_20,
                lt_tax=lt_tax, ord_tax=ord_tax, niit=niit,
                total=lt_tax + ord_tax + niit, margin_0pct=margin, magi=magi)


# ─────────────────────────────────────────
# UI
# ─────────────────────────────────────────
with st.sidebar:
    st.markdown("#### 💰 포트폴리오 트래커")
    owner_sel = st.radio("소유자", ["전체", "윤선화", "김희돈"], label_visibility="collapsed")
    last_date = max(t["date"] for t in st.session_state.transactions if t["type"] in ("buy","sell"))
    st.caption(f"마지막 거래: {last_date}")
    st.divider()
    if st.button("로그아웃", use_container_width=True):
        st.session_state.auth = False
        st.rerun()

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "💼 현재 보유", "📊 손익 분석", "📅 시점별 조회",
    "📋 거래 내역", "🇺🇸 US 세금 계산", "📝 거래 편집",
])


# ── Tab 1: 현재 보유 ─────────────────────
with tab1:
    st.subheader("현재 보유 종목")
    owners_show = ["윤선화", "김희돈"] if owner_sel == "전체" else [owner_sel]
    for owner in owners_show:
        positions = st.session_state.current_positions.get(owner, [])
        rows, tc, te = [], 0, 0
        for pos in positions:
            rt   = fetch_realtime(pos["code"])
            cur  = rt["price"] if rt else None
            cost = pos["avg_price"] * pos["shares"]
            ev   = cur * pos["shares"] if cur else None
            gain = (ev - cost) if ev is not None else None
            pct  = (gain / cost * 100) if gain is not None and cost else None
            tc  += cost
            if ev: te += ev
            rows.append({
                "종목": pos["name"], "보유주": f"{pos['shares']:,}",
                "평균매입가": fmt_krw(pos["avg_price"]), "매입금액": fmt_krw(cost),
                "현재가": fmt_krw(cur) if cur else "조회 중",
                "평가금액": fmt_krw(ev), "손익": fmt_krw(gain), "수익률": fmt_pct(pct),
            })
        tg = te - tc if te else None
        tp = (tg / tc * 100) if tg and tc else None
        with st.expander(
            f"**{owner}**  매입 {fmt_krw(tc)}  |  평가 {fmt_krw(te) if te else '-'}  |  손익 {fmt_krw(tg)}  ({fmt_pct(tp)})",
            expanded=True
        ):
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Tab 2: 손익 분석 ─────────────────────
with tab2:
    st.subheader("손익 분석")
    owner_f = None if owner_sel == "전체" else owner_sel

    # 기간 필터
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        p2_start = st.date_input("조회 시작일", value=date(2020, 1, 1), key="p2_start")
    with col_d2:
        p2_end = st.date_input("조회 종료일", value=date.today(), key="p2_end")

    realized = compute_realized_gains(
        owner_filter=owner_f,
        start_date=p2_start.strftime("%Y-%m-%d"),
        end_date=p2_end.strftime("%Y-%m-%d"),
    )

    # 실현 손익 테이블
    st.markdown("#### 실현 손익 (FIFO 기준)")
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
            rows_r.append({
                "연도": yr, "소유자": owner, "종목": name,
                "매입원가": fmt_krw(v["cost"]), "매도금액": fmt_krw(v["proceeds"]),
                "실현손익": fmt_krw(v["gain"]),
                "장기LT": fmt_krw(v["lt"]), "단기ST": fmt_krw(v["st"]),
            })
        df_r = pd.DataFrame(rows_r)
        if owner_sel != "전체":
            df_r = df_r.drop(columns=["소유자"])
        st.dataframe(df_r, use_container_width=True, hide_index=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("총 실현손익", fmt_krw(sum(r["gain"] for r in realized)))
        c2.metric("장기(LT)", fmt_krw(sum(r["gain"] for r in realized if r["is_lt"])))
        c3.metric("단기(ST)", fmt_krw(sum(r["gain"] for r in realized if not r["is_lt"])))

        with st.expander("상세 내역 (건별)"):
            rows_det = []
            for r in sorted(realized, key=lambda x: x["sell_date"]):
                rows_det.append({
                    "매도일": r["sell_date"], "소유자": r["owner"], "종목": r["name"],
                    "구분": "LT" if r["is_lt"] else "ST", "보유일": r["holding_days"],
                    "매입단가": fmt_krw(r["cost_per_share"]), "매도단가": fmt_krw(r["sell_per_share"]),
                    "수량": f"{r['shares']:.0f}", "손익": fmt_krw(r["gain"]),
                })
            df_det = pd.DataFrame(rows_det)
            if owner_sel != "전체":
                df_det = df_det.drop(columns=["소유자"])
            st.dataframe(df_det, use_container_width=True, hide_index=True)
    else:
        st.info("조회 기간 내 실현 손익 없음")

    st.divider()

    # 누적 투자금 차트
    st.markdown("#### 누적 순투자금 흐름")
    cf = cumulative_cashflow()
    if not cf.empty:
        if owner_sel != "전체":
            cf = cf[cf["owner"] == owner_sel]
        fig = go.Figure()
        colors = {"윤선화": "#10B981", "김희돈": "#F59E0B"}
        for o in cf["owner"].unique():
            sub = cf[cf["owner"] == o].sort_values("date")
            fig.add_trace(go.Scatter(
                x=sub["date"], y=sub["cumulative"], mode="lines", name=o,
                line=dict(color=colors.get(o, "#888"), width=2),
            ))
        fig.update_layout(
            yaxis_title="누적 순투자금 (원)", xaxis_title="",
            legend=dict(orientation="h", y=1.1), height=350,
            margin=dict(l=0, r=0, t=20, b=0),
        )
        fig.update_yaxes(tickformat=",")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("누적 순투자금 = 누적 매수금액 − 누적 매도금액")


# ── Tab 3: 시점별 조회 ───────────────────
with tab3:
    st.subheader("시점별 보유현황 조회")
    col_q1, col_q2 = st.columns([3, 1])
    with col_q1:
        query_date = st.date_input("조회 날짜", value=date.today(),
                                   min_value=date(2020, 1, 1), max_value=date.today())
    with col_q2:
        fetch_prices = st.checkbox("시점 주가 조회", value=False,
                                   help="pykrx로 해당일 종가를 가져옵니다. 느릴 수 있습니다.")

    owner_f3 = None if owner_sel == "전체" else owner_sel
    holdings = compute_holdings_at(query_date.strftime("%Y-%m-%d"), owner_filter=owner_f3)

    if holdings:
        rows3, tc3, te3 = [], 0, 0
        for h in sorted(holdings, key=lambda x: (x["owner"], x["name"])):
            hist_price = None
            if fetch_prices:
                hist_price = get_price_at_date(h["code"], query_date.strftime("%Y-%m-%d"))
            ev   = hist_price * h["shares"] if hist_price else None
            gain = (ev - h["total_cost"]) if ev else None
            pct  = (gain / h["total_cost"] * 100) if gain and h["total_cost"] else None
            tc3 += h["total_cost"]
            if ev: te3 += ev
            rows3.append({
                "소유자": h["owner"], "종목": h["name"], "코드": h["code"],
                "보유주": f"{h['shares']:.0f}",
                "평균매입가": fmt_krw(h["avg_price"]),
                "매입금액": fmt_krw(h["total_cost"]),
                "시점주가": fmt_krw(hist_price) if hist_price else ("-" if not fetch_prices else "조회 실패"),
                "시점평가": fmt_krw(ev),
                "손익": fmt_krw(gain),
                "수익률": fmt_pct(pct),
            })
        df3 = pd.DataFrame(rows3)
        if owner_sel != "전체":
            df3 = df3.drop(columns=["소유자"])
        if not fetch_prices:
            df3 = df3.drop(columns=["시점주가", "시점평가", "손익", "수익률"])
        st.dataframe(df3, use_container_width=True, hide_index=True)

        mc1, mc2 = st.columns(2)
        mc1.metric("총 투자금 (해당 시점)", fmt_krw(tc3))
        if te3:
            mc2.metric("총 평가금 (해당 시점)", fmt_krw(te3),
                       delta=f"{fmt_krw(te3-tc3)} ({fmt_pct((te3-tc3)/tc3*100)})")
    else:
        st.info(f"{query_date} 기준 보유 종목 없음")


# ── Tab 4: 거래 내역 ─────────────────────
with tab4:
    st.subheader("전체 거래 내역")
    txns4 = [t for t in st.session_state.transactions if t["type"] in ("buy", "sell")]
    if owner_sel != "전체":
        txns4 = [t for t in txns4 if t["owner"] == owner_sel]

    col_a, col_b = st.columns(2)
    with col_a:
        type_f = st.multiselect("거래유형", ["buy", "sell"], default=["buy", "sell"],
                                format_func=lambda x: "매수" if x == "buy" else "매도")
    with col_b:
        stocks_in = sorted(set(t["name"] for t in txns4))
        stock_f   = st.multiselect("종목 필터", stocks_in, default=stocks_in)

    txns4 = [t for t in txns4 if t["type"] in type_f and t["name"] in stock_f]
    rows4 = []
    for t in sorted(txns4, key=lambda x: x["date"], reverse=True):
        rows4.append({
            "날짜": t["date"], "소유자": t["owner"], "종목": t["name"],
            "구분": "매수" if t["type"] == "buy" else "매도",
            "단가": fmt_krw(t["price"]), "수량": f"{int(t['shares']):,}",
            "금액": fmt_krw(t["price"] * t["shares"]), "비고": t.get("note", ""),
        })
    df4 = pd.DataFrame(rows4)
    if owner_sel != "전체":
        df4 = df4.drop(columns=["소유자"])
    st.dataframe(df4, use_container_width=True, hide_index=True)
    st.caption(f"총 {len(rows4)}건")


# ── Tab 5: US 세금 계산 ──────────────────
with tab5:
    st.subheader("🇺🇸 US 세금 계산기 (MFJ · FEIE)")
    gist_ok = bool(_gist_id() and _gh_headers())
    save_col, info_col = st.columns([1, 4])
    with save_col:
        if st.button("💾 설정 저장", use_container_width=True,
                     help="입력값을 GitHub Gist에 저장합니다 (리프레시 후에도 유지)"):
            if save_tax_settings():
                st.success("저장됨")
            else:
                st.warning("저장 실패 — Secrets에 [github] 섹션을 추가하세요")
    with info_col:
        if gist_ok:
            st.caption("💡 Gist 연결됨 — '설정 저장' 클릭 시 리프레시 후에도 유지됩니다")
        else:
            st.caption("⚠️ Gist 미연결 — 설정이 세션 내에서만 유지됩니다. Secrets에 [github] 섹션을 추가하면 영구 저장됩니다")

    with st.expander("⚙️ 세율 파라미터 (클릭하여 수정)", expanded=False):
        pp1, pp2 = st.columns(2)
        with pp1:
            st.number_input("표준공제 (MFJ, USD)", min_value=0, step=100, key="tx_std_ded")
            st.number_input("LT 0% 상한 (과세소득, USD)", min_value=0, step=1000, key="tx_lt0")
            st.number_input("LT 15% 상한 (과세소득, USD)", min_value=0, step=1000, key="tx_lt15")
        with pp2:
            st.number_input("NIIT 기준 MAGI (MFJ, USD)", min_value=0, step=1000, key="tx_niit")
            st.number_input("FEIE 1인 한도 (USD)", min_value=0, step=1000, key="tx_feie_cap")

    st.divider()
    tc1, tc2 = st.columns(2)
    with tc1:
        st.number_input("적용 환율 (₩/USD)", min_value=500, max_value=2000, step=10, key="tx_xrate")
        st.number_input("세금연도", min_value=2020, max_value=2030, step=1, key="tx_year")
    with tc2:
        owner_tax = st.radio("실현손익 소유자", ["전체", "윤선화", "김희돈"],
                             key="tax_owner", horizontal=True)

    st.divider()
    st.markdown("**근로소득 및 FEIE 입력 (USD)**")
    te1, te2 = st.columns(2)
    with te1:
        st.markdown("*김희돈*")
        st.number_input("근로소득", min_value=0, step=1000, key="tx_earn_kim")
        st.number_input(
            f"FEIE 제외금액 (최대 {st.session_state.tx_feie_cap:,})",
            min_value=0, max_value=st.session_state.tx_feie_cap, step=1000, key="tx_feie_kim",
        )
    with te2:
        st.markdown("*윤선화*")
        st.number_input("근로소득 ", min_value=0, step=1000, key="tx_earn_yoon")
        st.number_input(
            f"FEIE 제외금액  (최대 {st.session_state.tx_feie_cap:,})",
            min_value=0, max_value=st.session_state.tx_feie_cap, step=1000, key="tx_feie_yoon",
        )
    st.number_input("기타 소득 (배당·이자, USD)", min_value=0, step=100, key="tx_other")

    st.divider()

    owner_f5  = None if owner_tax == "전체" else owner_tax
    start5    = f"{int(st.session_state.tx_year)}-01-01"
    end5      = f"{int(st.session_state.tx_year)}-12-31"
    realized5 = compute_realized_gains(owner_filter=owner_f5, start_date=start5, end_date=end5)
    lt_krw    = sum(r["gain"] for r in realized5 if r["is_lt"])
    st_krw    = sum(r["gain"] for r in realized5 if not r["is_lt"])

    st.markdown(f"**{int(st.session_state.tx_year)}년 실현 손익 ({owner_tax})**")
    sm1, sm2, sm3 = st.columns(3)
    sm1.metric("LT 실현손익 (원)", fmt_krw(lt_krw))
    sm2.metric("ST 실현손익 (원)", fmt_krw(st_krw))
    sm3.metric("합계 (원)", fmt_krw(lt_krw + st_krw))

    if realized5:
        with st.expander("실현 손익 상세"):
            rows5 = []
            for r in sorted(realized5, key=lambda x: x["sell_date"]):
                rows5.append({
                    "매도일": r["sell_date"], "소유자": r["owner"], "종목": r["name"],
                    "구분": "LT" if r["is_lt"] else "ST", "보유일": r["holding_days"],
                    "매입단가": fmt_krw(r["cost_per_share"]), "매도단가": fmt_krw(r["sell_per_share"]),
                    "수량": f"{r['shares']:.0f}", "손익(원)": fmt_krw(r["gain"]),
                })
            df5 = pd.DataFrame(rows5)
            if owner_sel != "전체":
                df5 = df5.drop(columns=["소유자"])
            st.dataframe(df5, use_container_width=True, hide_index=True)

    st.divider()
    res = compute_us_tax(
        lt_krw, st_krw,
        float(st.session_state.tx_earn_kim), float(st.session_state.tx_earn_yoon),
        float(st.session_state.tx_feie_kim), float(st.session_state.tx_feie_yoon),
        float(st.session_state.tx_xrate), float(st.session_state.tx_other),
        float(st.session_state.tx_std_ded), float(st.session_state.tx_lt0),
        float(st.session_state.tx_lt15), float(st.session_state.tx_niit),
    )

    st.markdown("**계산 결과**")
    sr1, sr2, sr3, sr4 = st.columns(4)
    sr1.metric("LT 손익 (USD)", fmt_usd(res["lt_usd"]))
    sr2.metric("ST 손익 (USD)", fmt_usd(res["st_usd"]))
    sr3.metric("순근로소득 (FEIE후)", fmt_usd(res["net_earned"]))
    sr4.metric("MAGI", fmt_usd(res["magi"]))

    sr5, sr6, sr7 = st.columns(3)
    sr5.metric("LT 과세소득", fmt_usd(res["lt_taxable"]), help="표준공제 잔여 적용 후")
    sr6.metric("0% 적용 LT", fmt_usd(res["lt_0"]))
    sr7.metric("15% 적용 LT", fmt_usd(res["lt_15"]))

    sr8, sr9, sr10, sr11 = st.columns(4)
    sr8.metric("LT 세금", fmt_usd(res["lt_tax"]))
    sr9.metric("일반소득세", fmt_usd(res["ord_tax"]))
    sr10.metric("NIIT (3.8%)", fmt_usd(res["niit"]))
    sr11.metric("총 세금", fmt_usd(res["total"]))

    margin = res["margin_0pct"]
    if margin > 0:
        st.success(
            f"✅ LT 0% 구간까지 여유: **{fmt_usd(margin)}** (≈ {fmt_krw(margin * st.session_state.tx_xrate)})"
        )
    else:
        st.warning(f"⚠️ LT 0% 구간 초과: {fmt_usd(-margin)} 이미 15% 구간 진입")

    with st.expander("📋 계산 근거"):
        st.markdown(f"""
| 항목 | 금액 |
|------|------|
| LT 실현손익 (원→USD) | {fmt_krw(lt_krw)} → {fmt_usd(res['lt_usd'])} |
| ST 실현손익 (원→USD) | {fmt_krw(st_krw)} → {fmt_usd(res['st_usd'])} |
| 적용 환율 | ₩{st.session_state.tx_xrate:,}/USD |
| 순근로소득 (FEIE 제외 후) | {fmt_usd(res['net_earned'])} |
| 기타소득 | {fmt_usd(st.session_state.tx_other)} |
| 표준공제 (MFJ) | {fmt_usd(st.session_state.tx_std_ded)} |
| 일반 과세소득 | {fmt_usd(res['ord_taxable'])} |
| LT 과세소득 | {fmt_usd(res['lt_taxable'])} |
| LT @ 0% | {fmt_usd(res['lt_0'])} |
| LT @ 15% | {fmt_usd(res['lt_15'])} |
| LT @ 20% | {fmt_usd(res['lt_20'])} |
| LT 세금 | {fmt_usd(res['lt_tax'])} |
| 일반소득세 | {fmt_usd(res['ord_tax'])} |
| NIIT (3.8%) | {fmt_usd(res['niit'])} |
| **총 세금** | **{fmt_usd(res['total'])}** |

> ⚠️ 참고용입니다. 실제 신고 전 세무사 확인 권장.
> LT 기준: 보유 365일 이상 | 한국 증권거래세·외국납부세액공제 별도 검토
        """)


# ── Tab 6: 거래 편집 ─────────────────────
with tab6:
    st.subheader("거래 편집")
    st.caption("변경사항은 현재 세션에만 유지됩니다. 영구 저장하려면 하단 JSON 내보내기로 Secrets를 업데이트하세요.")

    # ── 거래 추가
    with st.expander("➕ 거래 추가", expanded=False):
        with st.form("form_add"):
            fa1, fa2, fa3 = st.columns(3)
            with fa1:
                new_date  = st.date_input("날짜", value=date.today(), key="add_date")
                new_owner = st.selectbox("소유자", ["윤선화", "김희돈"], key="add_owner")
            with fa2:
                new_type  = st.selectbox("구분", ["buy", "sell"],
                                         format_func=lambda x: "매수" if x == "buy" else "매도",
                                         key="add_type")
                new_name  = st.text_input("종목명", key="add_name")
            with fa3:
                new_code   = st.text_input("종목코드 (예: 005930)", key="add_code")
                new_price  = st.number_input("단가 (원)", min_value=1, step=100, key="add_price")
                new_shares = st.number_input("수량", min_value=1, step=1, key="add_shares")
            new_note = st.text_input("비고 (선택)", key="add_note")

            if st.form_submit_button("✅ 추가", use_container_width=True):
                if new_name and new_code and new_price and new_shares:
                    entry = {
                        "date": new_date.strftime("%Y-%m-%d"),
                        "owner": new_owner, "code": new_code.strip(),
                        "name": new_name.strip(), "type": new_type,
                        "price": int(new_price), "shares": int(new_shares),
                    }
                    if new_note:
                        entry["note"] = new_note
                    st.session_state.transactions.append(entry)
                    st.success(f"✅ {new_name} {new_date} {new_type} 추가됨")
                    st.rerun()
                else:
                    st.error("종목명, 종목코드, 단가, 수량은 필수입니다.")

    st.divider()

    # ── 거래 삭제
    with st.expander("🗑️ 거래 삭제", expanded=False):
        del_owner = st.selectbox("삭제할 거래 소유자", ["전체", "윤선화", "김희돈"], key="del_owner")
        del_txns = [
            (i, t) for i, t in enumerate(st.session_state.transactions)
            if t["type"] in ("buy","sell")
            and (del_owner == "전체" or t["owner"] == del_owner)
        ]
        if del_txns:
            del_options = {
                i: f"{t['date']} | {t['owner']} | {t['name']} | {'매수' if t['type']=='buy' else '매도'} | {int(t['price']):,}원 × {int(t['shares'])}주"
                for i, t in del_txns
            }
            del_sel = st.multiselect("삭제할 항목 선택", options=list(del_options.keys()),
                                     format_func=lambda i: del_options[i])
            if del_sel and st.button("🗑️ 선택 항목 삭제", type="secondary"):
                for i in sorted(del_sel, reverse=True):
                    st.session_state.transactions.pop(i)
                st.success(f"{len(del_sel)}건 삭제됨")
                st.rerun()

    st.divider()

    # ── 거래 수정 (단가/수량)
    with st.expander("✏️ 거래 수정", expanded=False):
        edit_owner = st.selectbox("수정할 거래 소유자", ["전체", "윤선화", "김희돈"], key="edit_owner")
        edit_txns = [
            (i, t) for i, t in enumerate(st.session_state.transactions)
            if t["type"] in ("buy","sell")
            and (edit_owner == "전체" or t["owner"] == edit_owner)
        ]
        if edit_txns:
            edit_options = {
                i: f"{t['date']} | {t['owner']} | {t['name']} | {'매수' if t['type']=='buy' else '매도'} | {int(t['price']):,}원 × {int(t['shares'])}주"
                for i, t in edit_txns
            }
            edit_sel = st.selectbox("수정할 항목 선택", options=list(edit_options.keys()),
                                    format_func=lambda i: edit_options[i], key="edit_sel")
            if edit_sel is not None:
                t_orig = st.session_state.transactions[edit_sel]
                with st.form("form_edit"):
                    ec1, ec2, ec3 = st.columns(3)
                    with ec1:
                        e_date = st.date_input("날짜", value=datetime.strptime(t_orig["date"], "%Y-%m-%d").date())
                        e_owner = st.selectbox("소유자", ["윤선화","김희돈"],
                                               index=0 if t_orig["owner"]=="윤선화" else 1)
                    with ec2:
                        e_type = st.selectbox("구분", ["buy","sell"],
                                              index=0 if t_orig["type"]=="buy" else 1,
                                              format_func=lambda x: "매수" if x=="buy" else "매도")
                        e_name = st.text_input("종목명", value=t_orig["name"])
                    with ec3:
                        e_code   = st.text_input("종목코드", value=t_orig["code"])
                        e_price  = st.number_input("단가 (원)", min_value=1, value=int(t_orig["price"]), step=100)
                        e_shares = st.number_input("수량", min_value=1, value=int(t_orig["shares"]), step=1)
                    e_note = st.text_input("비고", value=t_orig.get("note",""))
                    if st.form_submit_button("💾 저장", use_container_width=True):
                        updated = {"date": e_date.strftime("%Y-%m-%d"), "owner": e_owner,
                                   "code": e_code.strip(), "name": e_name.strip(),
                                   "type": e_type, "price": int(e_price), "shares": int(e_shares)}
                        if e_note: updated["note"] = e_note
                        st.session_state.transactions[edit_sel] = updated
                        st.success("수정 완료")
                        st.rerun()

    st.divider()

    # ── 현재 거래 목록 보기
    st.markdown("**현재 거래 목록**")
    view_owner = None if owner_sel == "전체" else owner_sel
    view_txns  = [t for t in st.session_state.transactions if t["type"] in ("buy","sell")]
    if view_owner: view_txns = [t for t in view_txns if t["owner"] == view_owner]
    view_rows  = [{"날짜":t["date"],"소유자":t["owner"],"종목":t["name"],
                   "구분":"매수" if t["type"]=="buy" else "매도",
                   "단가":fmt_krw(t["price"]),"수량":f"{int(t['shares']):,}",
                   "금액":fmt_krw(t["price"]*t["shares"]),"비고":t.get("note","")}
                  for t in sorted(view_txns, key=lambda x: x["date"], reverse=True)]
    st.dataframe(pd.DataFrame(view_rows), use_container_width=True, hide_index=True)
    st.caption(f"총 {len(view_rows)}건")

    st.divider()

    # ── JSON 내보내기
    with st.expander("📤 JSON 내보내기 (Secrets 영구 저장용)"):
        st.markdown("""
**Streamlit Cloud → Settings → Secrets** 에서 `[data]` 섹션의 `transactions` 값을 아래 JSON으로 교체하세요.
        """)
        export_txn = json.dumps(st.session_state.transactions, ensure_ascii=False)
        st.code(f"transactions = '''\n{export_txn}\n'''", language="toml")

        st.markdown("**current_positions** (보유수량/평균단가 변경 시):")
        st.code(
            f"current_positions = '''\n{json.dumps(st.session_state.current_positions, ensure_ascii=False)}\n'''",
            language="toml"
        )

    if st.button("↩️ 원본으로 초기화", help="Secrets에 저장된 원본 데이터로 되돌립니다"):
        st.session_state.transactions     = list(_BASE_TXN)
        st.session_state.current_positions = dict(_BASE_POS)
        st.success("원본 데이터로 초기화 완료")
        st.rerun()
