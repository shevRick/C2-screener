import streamlit as st
import pandas as pd
import ccxt
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import tempfile

# Auto Refresh
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="C2 Closure Screener", page_icon="📈", layout="wide")

st.title("🧠 Smart Auto C2 Closure Screener")
st.markdown("**Auto-refreshes + Clickable TradingView Charts** | Deployed on Streamlit Cloud")

# ========================= SIDEBAR =========================
with st.sidebar:
    st.header("Configuration")
    
    default_symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 
                       'DOGE/USDT', 'ADA/USDT', 'AVAX/USDT', 'SUI/USDT', 'NEAR/USDT']
    
    all_symbols = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT', 'DOGE/USDT',
                   'ADA/USDT', 'AVAX/USDT', 'TRX/USDT', 'TON/USDT', 'SUI/USDT', 'LINK/USDT',
                   'DOT/USDT', 'NEAR/USDT', 'PEPE/USDT', 'ARB/USDT', 'OP/USDT']
    
    selected_symbols = st.multiselect("Select Coins", options=all_symbols, default=default_symbols)
    
    timeframes = st.multiselect("Timeframes", options=['1d', '4h', '1w'], default=['1d', '4h'])
    
    min_sweep = st.slider("Minimum Sweep %", 5, 50, 10, step=5) / 100.0
    refresh_interval = st.slider("Auto-refresh every (minutes)", 3, 15, 5)
    
    col1, col2 = st.columns(2)
    with col1:
        force_refresh = st.button("🔄 Force Full Refresh")
    with col2:
        st.info("Auto-refresh is ON")

# Auto Refresh
st_autorefresh(interval=refresh_interval * 60 * 1000, limit=None, key="c2autorefresh")

# Use temporary directory (Important for Streamlit Cloud)
CACHE_DIR = os.path.join(tempfile.gettempdir(), "c2_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# ========================= HELPERS =========================
def get_cache_filename(symbol, timeframe):
    return f"{CACHE_DIR}/{symbol.replace('/', '_')}_{timeframe}.csv"

def should_refresh_data(timeframe):
    now = datetime.utcnow()
    if timeframe == '4h':
        return (now.minute >= 5) and (now.hour % 4 in [0, 1])
    elif timeframe == '1d':
        return now.hour == 0 and now.minute >= 5
    elif timeframe == '1w':
        return now.weekday() == 0 and now.hour >= 1 and now.minute >= 10
    return False

def fetch_symbol_tf(args):
    symbol, tf = args
    try:
        exchange = ccxt.binance({'enableRateLimit': True})
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=80)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df.to_csv(get_cache_filename(symbol, tf))
        return symbol, tf, df
    except Exception as e:
        return symbol, tf, None

def load_from_cache(symbol, timeframe):
    try:
        return pd.read_csv(get_cache_filename(symbol, timeframe), index_col='timestamp', parse_dates=True)
    except:
        return None

def get_tradingview_url(symbol: str, timeframe: str) -> str:
    base = "https://www.tradingview.com/chart/?symbol=BINANCE:"
    tv_symbol = symbol.replace("/", "").upper()
    interval_map = {'1d': 'D', '4h': '240', '1w': 'W'}
    interval = interval_map.get(timeframe, 'D')
    return f"{base}{tv_symbol}&interval={interval}"

# ========================= SCAN FUNCTION =========================
def scan_latest_c2():
    results = []
    to_fetch = []
    data_dict = {}
    is_first_run = False
    debug_info = []

    for symbol in selected_symbols:
        for tf in timeframes:
            df = load_from_cache(symbol, tf)
            
            if force_refresh or df is None or len(df) < 4 or should_refresh_data(tf):
                to_fetch.append((symbol, tf))
                if df is None:
                    is_first_run = True
            else:
                data_dict[(symbol, tf)] = df

    if is_first_run and to_fetch:
        st.info(f"📥 First run: Downloading data for {len(to_fetch)} symbol-timeframe pairs...")

    # Parallel Fetch
    if to_fetch:
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(fetch_symbol_tf, pair) for pair in to_fetch]
            for future in as_completed(futures):
                symbol, tf, df = future.result()
                if df is not None:
                    data_dict[(symbol, tf)] = df
                else:
                    debug_info.append(f"❌ Failed to fetch {symbol} {tf}")

    # ==================== SCAN WITH DEBUG ====================
    for symbol in selected_symbols:
        for tf in timeframes:
            df = data_dict.get((symbol, tf))
            if df is None or len(df) < 4:
                debug_info.append(f"⚠️ Not enough data: {symbol} {tf} (rows: {len(df) if df is not None else 0})")
                continue

            i = len(df) - 1
            c1 = df.iloc[i-2]
            c2 = df.iloc[i-1]
            c3 = df.iloc[i]

            prev_range = c1['high'] - c1['low']
            if prev_range <= 0:
                continue

            c2_type = None
            sweep_pct = None

            # Bullish C2
            if c2['low'] < c1['low']:
                sweep_pct = (c1['low'] - c2['low']) / prev_range * 100
                if sweep_pct >= (min_sweep * 100) and c2['close'] > c1['low']:
                    c2_type = "Bullish C2"
            
            # Bearish C2
            elif c2['high'] > c1['high']:
                sweep_pct = (c2['high'] - c1['high']) / prev_range * 100
                if sweep_pct >= (min_sweep * 100) and c2['close'] < c1['high']:
                    c2_type = "Bearish C2"

            if c2_type:
                tv_url = get_tradingview_url(symbol, tf)
                results.append({
                    'Symbol': symbol,
                    'Timeframe': tf,
                    'C2 Date': c2.name.strftime('%Y-%m-%d %H:%M'),
                    'C2 Type': c2_type,
                    'C2 Close': round(float(c2['close']), 4),
                    'Current Price': round(float(c3['close']), 4),
                    '% Change': round((c3['close'] - c2['close']) / c2['close'] * 100, 2),
                    'Sweep %': round(sweep_pct, 2),
                    'View Chart': tv_url
                })
            else:
                # Debug: Show why it didn't trigger
                if sweep_pct:
                    debug_info.append(f"No C2: {symbol} {tf} | Sweep = {round(sweep_pct,2)}% (Min required: {min_sweep*100}%)")

    # Show debug info in expander
    if debug_info:
        with st.expander("🔍 Debug Information (Why no signals?)", expanded=True):
            for msg in debug_info[:20]:   # Show first 20 messages
                st.write(msg)

    return pd.DataFrame(results)

# ========================= MAIN =========================
if selected_symbols:
    df_results = scan_latest_c2()

    last_run = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    st.caption(f"Last checked: **{last_run}** | Auto-refreshing every {refresh_interval} minutes")

    if not df_results.empty:
        st.success(f"✅ Found **{len(df_results)}** Latest C2 Closure(s)")

        df_display = df_results.copy()
        df_display['Symbol'] = df_display.apply(
            lambda row: f'<a href="{row["View Chart"]}" target="_blank">{row["Symbol"]}</a>', 
            axis=1
        )

        st.write(
            df_display.style.applymap(
                lambda x: 'background-color: #008000' if x == "Bullish C2" else 
                         ('background-color: #FF0000' if x == "Bearish C2" else ''),
                subset=['C2 Type']
            ).to_html(escape=False, index=False),
            unsafe_allow_html=True
        )
    else:
        st.info("No C2 closure detected on the latest closed candles.")
else:
    st.warning("Please select at least one symbol.")

with st.expander("ℹ️ How It Works"):
    st.write("""
    - First run will download data for all selected symbols.
    - Subsequent refreshes use cache when possible.
    - Only fetches new data after a new 4H / Daily / Weekly candle closes.
    - Click any **Symbol** to open TradingView chart.
    """)
