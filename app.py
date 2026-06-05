import streamlit as st
import pandas as pd
import ccxt
import time
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="C2 Closure Screener", page_icon="📈", layout="wide")

st.title("🧠 Smart Auto C2 Closure Screener")
st.markdown("**Auto-refreshes + Clickable TradingView Charts**")

# ========================= SIDEBAR =========================
with st.sidebar:
    st.header("Configuration")
    
    default_symbols = ['BTC/USDT', 'ETH/USDT', 'NEIRO/USDT', 'FLOKI/USDT', 'WLD/USDT', 
                       'EPIC/USDT', 'ADA/USDT', 'AVAX/USDT', 'SUI/USDT',
                       'ENA/USDT', 'AR/USDT', 'SUSHI/USDT', 'JTO/USDT', 'VVV/USDT', 
                       'MEME/USDT', 'SPX/USDT', 'GRASS/USDT', 'ORDI/USDT',  'FET/USDT', 'DODOX/USDT', 'EIGEN/USDT',
                       'ETHFI/USDT', 'W/USDT', 'HFT/USDT', 'SSV/USDT', 'ONDO/USDT']
    
    all_symbols = ['BTC/USDT', 'ETH/USDT', 'NEIRO/USDT', 'FLOKI/USDT', 'WLD/USDT', 
                    'EPIC/USDT', 'ADA/USDT', 'AVAX/USDT', 'SUI/USDT',
                    'ENA/USDT', 'AR/USDT', 'SUSHI/USDT', 'JTO/USDT', 'VVV/USDT', 
                    'MEME/USDT', 'SPX/USDT', 'GRASS/USDT', 'ORDI/USDT',  'FET/USDT', 'DODOX/USDT', 'EIGEN/USDT',
                    'ETHFI/USDT', 'W/USDT', 'HFT/USDT', 'SSV/USDT', 'ONDO/USDT']
    
    selected_symbols = st.multiselect("Select Coins", options=all_symbols, default=default_symbols)
    
    timeframes = st.multiselect("Timeframes", options=['1d', '4h', '1w'], default=['1d', '4h'])
    
    min_sweep = st.slider("Minimum Sweep %", 5, 50, 10, step=5) / 100.0
    refresh_interval = st.slider("Auto-refresh every (minutes)", 3, 15, 5)
    
    col1, col2 = st.columns(2)
    with col1:
        force_refresh = st.button("Force Full Refresh")
    with col2:
        st.info("Auto-refresh is ON")

st_autorefresh(interval=refresh_interval * 60 * 1000, limit=None, key="c2autorefresh")

CACHE_DIR = "data_cache"
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
        st.error(f"Failed to fetch {symbol} {tf}: {e}")
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

# ========================= MAIN SCAN FUNCTION (FIXED) =========================
def scan_latest_c2():
    results = []
    to_fetch = []
    data_dict = {}
    cache_missing = False

    for symbol in selected_symbols:
        for tf in timeframes:
            df = load_from_cache(symbol, tf)
            
            # NEW LOGIC: Fetch if cache missing OR force refresh OR new candle
            if force_refresh or df is None or len(df) < 4 or should_refresh_data(tf):
                to_fetch.append((symbol, tf))
                if df is None:
                    cache_missing = True
            else:
                data_dict[(symbol, tf)] = df

    # Show status
    if cache_missing:
        st.info(f"📥 Downloading initial data for {len(to_fetch)} symbol-timeframe pairs... (First run)")
    elif to_fetch:
        st.info(f"📥 Fetching new candles for {len(to_fetch)} pairs...")

    # Parallel Fetch
    if to_fetch:
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(fetch_symbol_tf, pair) for pair in to_fetch]
            for future in as_completed(futures):
                symbol, tf, df = future.result()
                if df is not None:
                    data_dict[(symbol, tf)] = df

    # Scan for C2
    for symbol in selected_symbols:
        for tf in timeframes:
            df = data_dict.get((symbol, tf))
            if df is None or len(df) < 4:
                continue

            i = len(df) - 1
            c1 = df.iloc[i-2]
            c2 = df.iloc[i-1]
            c3 = df.iloc[i]

            prev_range = c1['high'] - c1['low']
            if prev_range <= 0:
                continue

            c2_type = None
            if c2['low'] < c1['low']:
                sweep_pct = (c1['low'] - c2['low']) / prev_range
                if sweep_pct >= min_sweep and c2['close'] > c1['low']:
                    c2_type = "Bullish C2"
            elif c2['high'] > c1['high']:
                sweep_pct = (c2['high'] - c1['high']) / prev_range
                if sweep_pct >= min_sweep and c2['close'] < c1['high']:
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
                    'View Chart': tv_url
                })

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
