import streamlit as st
import yfinance as yf
from pykrx import stock as krx_stock
import requests
from datetime import date, timedelta
from supabase import create_client

supabase = create_client(
    st.secrets["SUPABASE_URL"],
    st.secrets["SUPABASE_KEY"],
)


def load_holdings():
    res = supabase.table("holdings").select("*").execute()
    return res.data or []


def add_holding(holding):
    supabase.table("holdings").insert(holding).execute()


def update_holding_qty(ticker, quantity):
    supabase.table("holdings").update({"quantity": quantity}).eq("ticker", ticker).execute()


def delete_holding(ticker):
    supabase.table("holdings").delete().eq("ticker", ticker).execute()


def is_korean_stock(ticker):
    return ticker.isdigit() and len(ticker) == 6


def get_current_price(ticker):
    try:
        if is_korean_stock(ticker):
            today = date.today().strftime("%Y%m%d")
            start = (date.today() - timedelta(days=10)).strftime("%Y%m%d")
            df = krx_stock.get_market_ohlcv_by_date(start, today, ticker)
            if not df.empty:
                return float(df["종가"].iloc[-1])
            df = krx_stock.get_etf_ohlcv_by_date(start, today, ticker)
            if not df.empty:
                return float(df["종가"].iloc[-1])
        else:
            t = yf.Ticker(ticker)
            try:
                price = t.fast_info.last_price
                if price and price > 0:
                    return float(price)
            except Exception:
                pass
            hist = t.history(period="2d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def _naver_name(ticker):
    try:
        url = f"https://m.stock.naver.com/api/stock/{ticker}/basic"
        resp = requests.get(url, timeout=4, headers={"User-Agent": "Mozilla/5.0"})
        if resp.ok:
            data = resp.json()
            return data.get("stockName") or data.get("name")
    except Exception:
        pass
    return None


def get_stock_name(ticker):
    if is_korean_stock(ticker):
        try:
            name = krx_stock.get_market_ticker_name(ticker)
            if name:
                return name
        except Exception:
            pass
        name = _naver_name(ticker)
        return name if name else ticker
    else:
        try:
            info = yf.Ticker(ticker).info
            return info.get("shortName") or info.get("longName") or ticker
        except Exception:
            return ticker


@st.cache_data(ttl=3600)
def lookup_stock_name(ticker):
    return get_stock_name(ticker)


@st.cache_data(ttl=300)
def get_usdkrw():
    try:
        t = yf.Ticker("USDKRW=X")
        try:
            rate = t.fast_info.last_price
            if rate and rate > 0:
                return float(rate)
        except Exception:
            pass
        hist = t.history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return 1350.0


def fmt_money(value, currency):
    if value is None:
        return "—"
    if currency == "KRW":
        return f"₩{value:,.0f}"
    else:
        return f"${value:,.2f}"


def to_display(value_native, native_market, display_currency, usdkrw):
    if value_native is None:
        return None
    if display_currency == "각자 통화":
        return value_native, "KRW" if native_market == "KR" else "USD"
    if display_currency == "원화(₩)":
        converted = value_native if native_market == "KR" else value_native * usdkrw
        return converted, "KRW"
    converted = value_native / usdkrw if native_market == "KR" else value_native
    return converted, "USD"


# ── 페이지 설정 ─────────────────────────────────────────────────────────────
st.set_page_config(page_title="주식 포트폴리오", page_icon="📈", layout="wide")
st.title("📈 주식 포트폴리오 관리")

holdings = load_holdings()

# ── 사이드바 ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("종목 추가")
    st.caption("한국: 6자리 숫자 (예: 005930)\n미국: 영문 티커 (예: AAPL)")

    ticker_input = st.text_input("티커", placeholder="005930 / AAPL")

    preview_name = None
    ticker_valid = False
    if ticker_input.strip():
        raw = ticker_input.strip()
        ticker_preview = raw if raw.isdigit() else raw.upper()
        with st.spinner("종목명 조회 중..."):
            preview_name = lookup_stock_name(ticker_preview)
        if preview_name and preview_name != ticker_preview:
            st.success(f"**{preview_name}**")
            ticker_valid = True
        else:
            st.info("종목명을 찾지 못했습니다. 그래도 추가할 수 있습니다.")
            preview_name = ticker_preview
            ticker_valid = True

    quantity = st.number_input("수량", min_value=0.0001, step=1.0, format="%.4f")

    if st.button("추가", type="primary", use_container_width=True):
        raw = ticker_input.strip()
        if not raw:
            st.error("티커를 입력하세요.")
        elif not ticker_valid:
            st.error("티커를 먼저 입력하세요.")
        else:
            ticker = raw if raw.isdigit() else raw.upper()
            if any(h["ticker"] == ticker for h in holdings):
                st.error(f"{ticker} 는 이미 등록된 종목입니다.")
            else:
                market = "KR" if is_korean_stock(ticker) else "US"
                add_holding({
                    "ticker": ticker,
                    "name": preview_name,
                    "quantity": quantity,
                    "market": market,
                })
                st.rerun()

    st.divider()

    display_currency = st.radio(
        "표시 통화",
        ["각자 통화", "원화(₩)", "달러($)"],
        index=1,
    )

    st.divider()

    if st.button("🔄 시세 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ── 데이터 없음 ──────────────────────────────────────────────────────────────
if not holdings:
    st.info("왼쪽 사이드바에서 종목을 추가하세요.")
    st.stop()

# ── 환율 조회 ────────────────────────────────────────────────────────────────
usdkrw = get_usdkrw()
st.caption(f"USD/KRW 환율: ₩{usdkrw:,.1f}  ·  기준시각: {date.today()}")

# ── 시세 조회 ────────────────────────────────────────────────────────────────
with st.spinner("실시간 시세 조회 중..."):
    rows = []
    for h in holdings:
        price = get_current_price(h["ticker"])
        qty = h["quantity"]
        market = h["market"]
        cur_val = price * qty if price is not None else None
        rows.append(dict(
            ticker=h["ticker"],
            name=h["name"],
            market=market,
            quantity=qty,
            price=price,
            cur_val=cur_val,
        ))

# ── 요약 지표 ────────────────────────────────────────────────────────────────
kr_rows = [r for r in rows if r["market"] == "KR"]
us_rows = [r for r in rows if r["market"] == "US"]

kr_val_native = sum(r["cur_val"] for r in kr_rows if r["cur_val"] is not None)
us_val_native = sum(r["cur_val"] for r in us_rows if r["cur_val"] is not None)

c1, c2, c3 = st.columns(3)
with c1:
    kr_disp, kr_cur = to_display(kr_val_native, "KR", display_currency, usdkrw)
    st.metric("🇰🇷 한국 주식 평가액", fmt_money(kr_disp, kr_cur))
with c2:
    us_disp, us_cur = to_display(us_val_native, "US", display_currency, usdkrw)
    st.metric("🇺🇸 미국 주식 평가액", fmt_money(us_disp, us_cur))
with c3:
    total_kr, _ = to_display(kr_val_native, "KR", display_currency, usdkrw)
    total_us, _ = to_display(us_val_native, "US", display_currency, usdkrw)
    total = (total_kr or 0) + (total_us or 0)
    _, total_cur = to_display(1, "KR" if display_currency != "달러($)" else "US", display_currency, usdkrw)
    st.metric("💰 총 평가액", fmt_money(total, total_cur))

st.divider()

# ── 종목 테이블 ──────────────────────────────────────────────────────────────
if "editing" not in st.session_state:
    st.session_state.editing = None


def render_table(target_rows, ns):
    header = st.columns([0.5, 3, 1.6, 1.5, 1.8, 0.6, 0.6])
    for col, label in zip(header, ["#", "종목명", "수량", "현재가", "평가액", "", ""]):
        col.markdown(f"**{label}**")
    st.markdown("---")

    for i, r in enumerate(target_rows, 1):
        market = r["market"]
        ticker = r["ticker"]
        is_editing = st.session_state.editing == ticker

        def disp(native_val, _market=market):
            v, cur = to_display(native_val, _market, display_currency, usdkrw)
            return fmt_money(v, cur)

        cols = st.columns([0.5, 3, 1.6, 1.5, 1.8, 0.6, 0.6])
        cols[0].write(str(i))
        cols[1].write(f"**{r['name']}**\n\n`{ticker}`")

        if is_editing:
            new_qty = cols[2].number_input(
                "수량", value=float(r["quantity"]),
                min_value=0.0001, step=1.0, format="%.4f",
                key=f"{ns}_qty_{ticker}", label_visibility="collapsed"
            )
            cols[3].write(disp(r["price"]) if r["price"] is not None else "⚠️ 조회 실패")
            cols[4].write(disp(r["price"] * new_qty) if r["price"] is not None else "—")
            if cols[5].button("✅", key=f"{ns}_save_{ticker}", help="저장"):
                update_holding_qty(ticker, new_qty)
                st.session_state.editing = None
                st.rerun()
            if cols[6].button("✖️", key=f"{ns}_cancel_{ticker}", help="취소"):
                st.session_state.editing = None
                st.rerun()
        else:
            cols[2].write(f"{r['quantity']:g}")
            cols[3].write(disp(r["price"]) if r["price"] is not None else "⚠️ 조회 실패")
            cols[4].write(disp(r["cur_val"]))
            if cols[5].button("✏️", key=f"{ns}_edit_{ticker}", help="수량 수정"):
                st.session_state.editing = ticker
                st.rerun()
            if cols[6].button("🗑️", key=f"{ns}_del_{ticker}", help="삭제"):
                delete_holding(ticker)
                st.rerun()


tab_all, tab_kr, tab_us = st.tabs(["전체", "🇰🇷 한국", "🇺🇸 미국"])

with tab_all:
    render_table(rows, "all")

with tab_kr:
    if kr_rows:
        render_table(kr_rows, "kr")
    else:
        st.info("보유한 한국 주식이 없습니다.")

with tab_us:
    if us_rows:
        render_table(us_rows, "us")
    else:
        st.info("보유한 미국 주식이 없습니다.")
