import streamlit as st
import yfinance as yf
import google.generativeai as genai
from datetime import datetime
import pytz
import pandas as pd
import json
import re
import time
import requests
import xml.etree.ElementTree as ET
from github import Github

# ==========================================
# 0. 설정
# ==========================================
USERS          = st.secrets["users"]
MY_API_KEY     = st.secrets["GEMINI_API_KEY"]
GITHUB_TOKEN   = st.secrets["GITHUB_TOKEN"]
REPO_NAME      = st.secrets["REPO_NAME"]
KIS_APP_KEY    = st.secrets["KIS_APP_KEY"]
KIS_APP_SECRET = st.secrets["KIS_APP_SECRET"]
KIS_BASE_URL   = "https://openapi.koreainvestment.com:9443"

def get_portfolio_file(username):
    return f"portfolio_{username}.json"

# ==========================================
# 1. KIS 토큰 발급
# ==========================================
def get_kis_token():
    url = f"{KIS_BASE_URL}/oauth2/tokenP"
    body = {
        "grant_type": "client_credentials",
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET
    }
    try:
        res = requests.post(url, json=body, timeout=10)
        return res.json().get("access_token", None)
    except:
        return None

# ==========================================
# 2. KIS - 종목명으로 코드 검색
# ==========================================
def search_stock_code(token, query):
    try:
        url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/search-stock-info"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": "CTPF1002R",
            "custtype": "P"
        }
        params = {"PRDT_TYPE_CD": "300", "PDNO": query}
        res = requests.get(url, headers=headers, params=params, timeout=5)
        output = res.json().get("output", {})
        code = output.get("shtn_pdno", "").strip()
        name = output.get("prdt_abrv_name", "").strip()
        return code, name
    except:
        return "", ""

# ==========================================
# 3. KIS - 종목 현재가 상세
# ==========================================
def get_kis_stock_detail(token, code):
    try:
        url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": "FHKST01010100",
            "custtype": "P"
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        res = requests.get(url, headers=headers, params=params, timeout=5)
        return res.json().get("output", {})
    except:
        return {}

# ==========================================
# 4. KIS - 투자자별 매매동향
# ==========================================
def get_kis_stock_investor(token, code):
    try:
        url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor"
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": KIS_APP_KEY,
            "appsecret": KIS_APP_SECRET,
            "tr_id": "FHKST01010900",
            "custtype": "P"
        }
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        res = requests.get(url, headers=headers, params=params, timeout=5)
        output = res.json().get("output", [])
        return [o for o in output if o.get("frgn_ntby_qty", "") != ""][:5]
    except:
        return []

# ==========================================
# 5. KIS - 주요 종목 수급
# ==========================================
def get_kis_foreign_buying(token):
    major_stocks = [
        ("삼성전자", "005930"), ("SK하이닉스", "000660"),
        ("현대차", "005380"), ("POSCO홀딩스", "005490"),
        ("LG에너지솔루션", "373220"),
    ]
    lines = []
    for name, code in major_stocks:
        try:
            url = f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-investor"
            headers = {
                "authorization": f"Bearer {token}",
                "appkey": KIS_APP_KEY,
                "appsecret": KIS_APP_SECRET,
                "tr_id": "FHKST01010900",
                "custtype": "P"
            }
            params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
            res = requests.get(url, headers=headers, params=params, timeout=5)
            output = res.json().get("output", [])
            item = next((o for o in output if o.get("frgn_ntby_qty", "") != ""), None)
            if item:
                frgn = item.get("frgn_ntby_qty", "0")
                inst = item.get("orgn_ntby_qty", "0")
                date = item.get("stck_bsop_date", "")
                date_str = f"{date[4:6]}/{date[6:8]}" if len(date) == 8 else ""
                lines.append(f"- {name}({code}) [{date_str}]: 외국인 {int(frgn):+,}주 | 기관 {int(inst):+,}주")
        except:
            continue
    return "\n".join(lines) if lines else "수급 데이터 없음"

# ==========================================
# 6. 거래량 - yfinance
# ==========================================
def get_volume_rank():
    major_stocks = [
        ("삼성전자", "005930.KS"), ("SK하이닉스", "000660.KS"),
        ("현대차", "005380.KS"), ("카카오", "035720.KS"), ("NAVER", "035420.KS"),
    ]
    lines = []
    for name, code in major_stocks:
        try:
            data = yf.Ticker(code).history(period="2d").dropna()
            if len(data) >= 2:
                vol  = int(data["Volume"].iloc[-1])
                curr = data["Close"].iloc[-1]
                prev = data["Close"].iloc[-2]
                chg  = ((curr - prev) / prev) * 100
                sign = "▲" if chg > 0 else "▼"
                lines.append(f"- {name}: 거래량 {vol:,}주 | {curr:,.0f}원 ({sign}{abs(chg):.2f}%)")
        except:
            continue
    return "\n".join(lines) if lines else "거래량 데이터 없음"

# ==========================================
# 7. 기술적 지표
# ==========================================
def calc_indicators(ticker_code):
    try:
        data = yf.Ticker(ticker_code).history(period="3mo").dropna()
        if len(data) < 26:
            return None
        close = data["Close"]
        high  = data["High"]
        low   = data["Low"]

        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = round((100 - (100 / (1 + gain/loss))).iloc[-1], 1)

        ema12  = close.ewm(span=12).mean()
        ema26  = close.ewm(span=26).mean()
        macd   = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        macd_cross = "골든크로스 ▲" if macd.iloc[-1] > signal.iloc[-1] else "데드크로스 ▼"

        ma20     = close.rolling(20).mean()
        std20    = close.rolling(20).std()
        upper    = ma20 + 2 * std20
        lower_bb = ma20 - 2 * std20
        bb_pos   = "상단 근접" if close.iloc[-1] > upper.iloc[-1] * 0.98 else \
                   "하단 근접" if close.iloc[-1] < lower_bb.iloc[-1] * 1.02 else "중간"

        lowest  = low.rolling(14).min()
        highest = high.rolling(14).max()
        stoch_k = round(((close - lowest) / (highest - lowest) * 100).iloc[-1], 1)

        ma5  = round(close.rolling(5).mean().iloc[-1], 0)
        ma20v = round(ma20.iloc[-1], 0)
        ma60 = round(close.rolling(60).mean().iloc[-1], 0) if len(data) >= 60 else None

        return {
            "rsi": rsi, "macd": macd_cross,
            "macd_val": round(macd.iloc[-1], 2), "signal_val": round(signal.iloc[-1], 2),
            "bb": bb_pos, "bb_upper": round(upper.iloc[-1], 0), "bb_lower": round(lower_bb.iloc[-1], 0),
            "stoch_k": stoch_k, "ma5": ma5, "ma20": ma20v, "ma60": ma60,
        }
    except:
        return None

# ==========================================
# 8. yfinance 코드 자동 판별 (KS/KQ)
# ==========================================
def find_yf_code(code):
    code = code.zfill(6)
    for suffix in [".KS", ".KQ"]:
        try:
            hist = yf.Ticker(f"{code}{suffix}").history(period="5d").dropna()
            if not hist.empty:
                return f"{code}{suffix}", hist
        except:
            continue
    return None, None

# ==========================================
# 9. 종목 관련 뉴스
# ==========================================
def get_stock_related_news(code, name=""):
    try:
        query = name if name else code
        url = f"https://news.google.com/rss/search?q={requests.utils.quote(query+' 주식')}&hl=ko&gl=KR&ceid=KR:ko"
        res  = requests.get(url, timeout=5)
        root = ET.fromstring(res.content)
        news = []
        for item in root.findall(".//item")[:5]:
            title = item.find("title")
            pub   = item.find("pubDate")
            if title is not None:
                news.append(f"- {title.text} ({pub.text[:16] if pub is not None else ''})")
        return "\n".join(news) if news else "관련 뉴스 없음"
    except:
        return "뉴스 조회 실패"

# ==========================================
# 10. 시장 전체 뉴스
# ==========================================
def get_stock_news():
    news_list = []
    queries = ["한국 주식", "코스피 코스닥", "증시 전망"]
    for query in queries:
        try:
            url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
            res = requests.get(url, timeout=5)
            root = ET.fromstring(res.content)
            for item in root.findall(".//item")[:3]:
                title = item.find("title")
                pub   = item.find("pubDate")
                if title is not None:
                    news_list.append(f"- {title.text} ({pub.text[:16] if pub is not None else ''})")
        except:
            continue
    return "\n".join(news_list) if news_list else "뉴스 조회 실패"

# ==========================================
# 11. 깃허브 JSON 읽기/쓰기
# ==========================================
def load_github_json(username):
    file_path = get_portfolio_file(username)
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        file_content = repo.get_contents(file_path)
        data = json.loads(file_content.decoded_content.decode())
        df = pd.DataFrame(data)
        if "별칭" not in df.columns:
            df["별칭"] = ""
        return df
    except:
        return pd.DataFrame(columns=["종목명", "보유수량", "평단가", "별칭"])

def save_github_json(df, username):
    file_path = get_portfolio_file(username)
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        data_str = df.to_json(orient='records', force_ascii=False)
        try:
            contents = repo.get_contents(file_path)
            repo.update_file(
                path=contents.path,
                message=f"Update portfolio - {username}",
                content=data_str,
                sha=contents.sha
            )
        except:
            repo.create_file(
                path=file_path,
                message=f"Initial portfolio - {username}",
                content=data_str
            )
        return True
    except Exception as e:
        st.error(f"❌ 저장 중 오류: {e}")
        return False

# ==========================================
# 12. 자동 저장
# ==========================================
def auto_save():
    editor_state = st.session_state["portfolio_editor"]
    df = st.session_state.portfolio.copy()
    for idx, edits in editor_state.get("edited_rows", {}).items():
        for col, val in edits.items():
            df.at[int(idx), col] = val
    for row in editor_state.get("added_rows", []):
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    deleted = editor_state.get("deleted_rows", [])
    df = df.drop(index=deleted).reset_index(drop=True)
    if save_github_json(df, st.session_state.username):
        st.session_state.portfolio = df

# ==========================================
# 13. 장 상태 판단
# ==========================================
def get_market_context():
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    weekday = now.weekday()
    hour = now.hour
    if weekday == 5:
        return now, "다음 월요일 장", "주말(토요일)이므로 다음 월요일 장 시작 전 분석"
    elif weekday == 6:
        return now, "내일 월요일 장", "주말(일요일)이므로 내일 월요일 장 시작 전 분석"
    elif hour < 9:
        return now, "오늘 장", "장 시작 전이므로 오늘 장 시작 기준 분석"
    elif hour < 16:
        return now, "오늘 장중", "현재 장중이므로 실시간 기준 분석"
    else:
        return now, "내일 장", "장 마감 이후이므로 내일 장 시작 기준 분석"

# ==========================================
# 14. 429 재시도
# ==========================================
def generate_with_retry(model, prompt, max_retries=3):
    for i in range(max_retries):
        try:
            return model.generate_content(prompt)
        except Exception as e:
            if "429" in str(e):
                wait = (i + 1) * 10
                st.warning(f"⏳ 요청 한도 초과. {wait}초 후 재시도... ({i+1}/{max_retries})")
                time.sleep(wait)
            else:
                raise e
    raise Exception("최대 재시도 횟수 초과")

# ==========================================
# 15. 메인 페이지
# ==========================================
st.set_page_config(page_title="AI 주식 비서 PRO", page_icon="📈", layout="centered")

for key in ['logged_in', 'username', 'portfolio', 'analysis_result',
            'analysis_time', 'market_lines', 'foreign_str', 'volume_str', 'news_str']:
    if key not in st.session_state:
        st.session_state[key] = False if key == 'logged_in' else None

# ==========================================
# 로그인
# ==========================================
if not st.session_state.logged_in:
    st.markdown("<h2 style='text-align: center;'>🔒 로그인</h2>", unsafe_allow_html=True)
    id_input = st.text_input("아이디")
    pw_input = st.text_input("비밀번호", type="password")
    if st.button("로그인", use_container_width=True):
        if id_input in USERS and USERS[id_input] == pw_input:
            st.session_state.logged_in = True
            st.session_state.username  = id_input
            st.session_state.portfolio = load_github_json(id_input)
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 틀렸습니다.")

# ==========================================
# 메인 앱
# ==========================================
else:
    now, target_period, market_context = get_market_context()
    username = st.session_state.username

    st.markdown(f"<h3 style='text-align: center;'>📱 {target_period} 맞춤형 리포트</h3>", unsafe_allow_html=True)
    st.caption(f"👤 {username} 님")

    tab1, tab2 = st.tabs(["🚀 AI 자산 진단", "🔍 종목 검색 분석"])

    # ==========================================
    # TAB 1: AI 자산 진단
    # ==========================================
    with tab1:
        with st.expander("💼 내 종목 관리", expanded=False):
            st.data_editor(
                st.session_state.portfolio,
                num_rows="dynamic",
                use_container_width=True,
                key="portfolio_editor",
                on_change=auto_save,
                column_config={
                    "종목명": st.column_config.TextColumn("종목코드", help="예: 005930.KS"),
                    "보유수량": st.column_config.NumberColumn("보유수량", min_value=0),
                    "평단가": st.column_config.NumberColumn("평단가(원)", min_value=0),
                    "별칭": st.column_config.TextColumn("한글명", help="예: 삼성전자우"),
                }
            )
            st.caption("✏️ 한글명 입력 시 분석에 해당 이름으로 표시됩니다")

        st.markdown("---")

        if st.button("🚀 AI 자산 진단 시작", use_container_width=True):
            with st.spinner("📡 시장 데이터 수집 중..."):
                try:
                    # [1단계] 시장 지수
                    tickers = {
                        "코스피": "^KS11", "코스닥": "^KQ11",
                        "달러/원": "KRW=X", "나스닥": "^IXIC", "S&P500": "^GSPC",
                    }
                    market_lines = []
                    for name, ticker in tickers.items():
                        try:
                            t = yf.Ticker(ticker)
                            data = t.history(period="5d").dropna()
                            if len(data) >= 2:
                                prev = data["Close"].iloc[-2]
                                curr = data["Close"].iloc[-1]
                                chg  = ((curr - prev) / prev) * 100
                                sign = "▲" if chg > 0 else "▼"
                                market_lines.append(f"{name}: {curr:,.2f} ({sign}{abs(chg):.2f}%)")
                            elif len(data) == 1:
                                market_lines.append(f"{name}: {data['Close'].iloc[-1]:,.2f}")
                        except:
                            market_lines.append(f"{name}: 조회 실패")
                    market_data_str = "\n".join(market_lines)

                    # [2단계] KIS 수급 + 거래량
                    with st.spinner("📊 수급/거래량 수집 중..."):
                        kis_token   = get_kis_token()
                        foreign_str = get_kis_foreign_buying(kis_token) if kis_token else "KIS 토큰 실패"
                        volume_str  = get_volume_rank()

                    # [3단계] 뉴스
                    with st.spinner("📰 뉴스 수집 중..."):
                        news_str = get_stock_news()

                    # [4단계] 포트폴리오
                    portfolio = st.session_state.portfolio.copy()
                    portfolio_lines = []
                    my_stock_codes = []

                    for _, row in portfolio.iterrows():
                        try:
                            종목명코드 = str(row["종목명"]).strip()
                            수량_raw   = row["보유수량"]
                            평단가_raw = row["평단가"]
                            if pd.isna(수량_raw) or pd.isna(평단가_raw): continue
                            if 종목명코드 in ["", "nan"]: continue
                            수량   = float(수량_raw)
                            평단가 = float(평단가_raw)
                            if 수량 <= 0 or 평단가 <= 0: continue
                            my_stock_codes.append(종목명코드)

                            별칭 = str(row.get("별칭", "")).strip()
                            if 별칭 and 별칭 != "nan":
                                실제종목명 = 별칭
                                hist = yf.Ticker(종목명코드).history(period="5d").dropna()
                                현재가 = float(hist["Close"].iloc[-1]) if not hist.empty else 평단가
                            else:
                                t_obj = yf.Ticker(종목명코드)
                                info  = t_obj.info
                                실제종목명 = info.get("longName") or info.get("shortName") or 종목명코드
                                hist = t_obj.history(period="5d").dropna()
                                현재가 = float(hist["Close"].iloc[-1]) if not hist.empty else 평단가

                            총매입 = 평단가 * 수량
                            총평가 = 현재가 * 수량
                            손익   = 총평가 - 총매입
                            손익률 = ((현재가 - 평단가) / 평단가) * 100
                            sign   = "▲" if 손익률 > 0 else "▼"
                            ind    = calc_indicators(종목명코드)
                            ind_str = f"RSI {ind['rsi']} | MACD {ind['macd']} | BB {ind['bb']} | 스토캐스틱 {ind['stoch_k']}" if ind else "지표 계산 불가"

                            portfolio_lines.append(
                                f"- {실제종목명}({종목명코드}): 현재가 {현재가:,.0f}원 | 평단 {평단가:,.0f}원 | "
                                f"{sign}{abs(손익률):.1f}% | 평가손익 {손익:+,.0f}원\n"
                                f"  기술지표: {ind_str}"
                            )
                        except:
                            continue

                    my_portfolio_str   = "\n".join(portfolio_lines) if portfolio_lines else "포트폴리오 없음"
                    my_stock_codes_str = ", ".join(my_stock_codes) if my_stock_codes else "없음"

                    # [5단계] AI 추천 종목
                    genai.configure(api_key=MY_API_KEY)
                    model = genai.GenerativeModel('gemini-2.5-flash')

                    with st.spinner("🤖 AI 추천 종목 선정 중..."):
                        prompt_ticker = f"""
당신은 대한민국 주식시장에서 30년 이상 활동한 최고 수익률의 전문 트레이더입니다.

[현재 시장 상황] {market_data_str}
[주요 종목 수급] {foreign_str}
[주요 종목 거래량] {volume_str}
[오늘의 실시간 뉴스] {news_str}
[분석 시점] {market_context}
[보유 종목 - 절대 추천 금지] {my_stock_codes_str}

조건:
- 보유 종목과 완전히 다른 종목
- 외국인/기관 순매수 활발한 종목 우선
- 거래량 증가 + 뉴스 모멘텀 종목
- {target_period} 흐름에 맞는 종목

아래 JSON 형식으로만 출력하세요:
[
  {{"name": "한글종목명", "code": "종목코드.KS또는.KQ", "reason": "추천이유"}},
  {{"name": "한글종목명", "code": "종목코드.KS또는.KQ", "reason": "추천이유"}},
  {{"name": "한글종목명", "code": "종목코드.KS또는.KQ", "reason": "추천이유"}}
]
"""
                        response_ticker = generate_with_retry(model, prompt_ticker)
                        json_str = re.search(r'\[.*\]', response_ticker.text, re.DOTALL).group()
                        recommend_list = json.loads(json_str)

                    # [6단계] 추천 종목 현재가 + 기술지표
                    recommend_lines = []
                    for item in recommend_list:
                        try:
                            hist = yf.Ticker(item["code"]).history(period="5d").dropna()
                            현재가 = float(hist["Close"].iloc[-1]) if not hist.empty else None
                            if 현재가:
                                매수가  = 현재가 * 0.97
                                목표가1 = 현재가 * 1.10
                                목표가2 = 현재가 * 1.20
                                손절가  = 현재가 * 0.93
                                ind = calc_indicators(item["code"])
                                ind_str = f"RSI {ind['rsi']} | MACD {ind['macd']} | BB {ind['bb']} | 스토캐스틱 {ind['stoch_k']}" if ind else "지표 계산 불가"
                                recommend_lines.append(
                                    f"- {item['name']} ({item['code']})\n"
                                    f"  현재가: {현재가:,.0f}원\n"
                                    f"  기술지표: {ind_str}\n"
                                    f"  추천이유: {item['reason']}\n"
                                    f"  매수시점: {매수가:,.0f}원 이하\n"
                                    f"  1차 목표가: {목표가1:,.0f}원 (+10%)\n"
                                    f"  2차 목표가: {목표가2:,.0f}원 (+20%)\n"
                                    f"  손절가: {손절가:,.0f}원 (-7%)"
                                )
                            else:
                                recommend_lines.append(f"- {item['name']}: 현재가 조회 실패")
                        except:
                            recommend_lines.append(f"- {item['name']}: 현재가 조회 실패")
                    recommend_str = "\n".join(recommend_lines)

                    # [7단계] 최종 AI 분석
                    with st.spinner("🤖 AI 최종 분석 중..."):
                        prompt = f"""
당신은 대한민국 주식시장에서 30년 이상 활동한 최고 수익률의 전문 트레이더입니다.
기술적 분석(RSI, MACD, 볼린저밴드, 스토캐스틱), 기본적 분석(PER, PBR),
섹터 로테이션, 외국인/기관 수급 분석까지 모두 활용합니다.

[분석 시점] {market_context}
[시장 정보] {market_data_str}
[주요 종목 수급] {foreign_str}
[주요 종목 거래량] {volume_str}
[오늘의 실시간 뉴스] {news_str}
[내 보유 자산 현황 + 기술지표] {my_portfolio_str}
[신규 추천 종목 실제 현재가 + 기술지표] {recommend_str}

아래 3가지를 모바일에서 읽기 편하게 세로 리스트로 작성하세요.

1. 📊 내 종목 진단
각 종목마다:
- 종목명 (코드)
- 현재 상태 (수익/손실 %)
- 기술지표 해석 (RSI/MACD/BB/스토캐스틱 종합)
- 진단: 유지 / 추가매수 / 일부매도 / 전량매도
- 근거: 수급+뉴스+기술지표 종합 2~3줄
- 매수 시점 / 매도 시점 (목표가 + 손절가)

2. 🔥 {target_period} 신규 추천 종목 3개
각 종목마다:
- 종목명 (코드)
- 현재가 (위 데이터 그대로)
- 기술지표 해석
- 추천 근거 3~4줄
- 매수 시점 / 1차·2차 목표가 / 손절가
- 투자 기간: 단기/중기/장기

3. 💬 전문가 총평
- 시장 흐름 평가
- 핵심 투자 전략 한 줄
- 리스크 경고
"""
                        response = generate_with_retry(model, prompt)
                        result_text = response.text

                    kst = pytz.timezone('Asia/Seoul')
                    st.session_state.analysis_result = result_text
                    st.session_state.analysis_time   = datetime.now(kst).strftime("%m/%d %H:%M")
                    st.session_state.market_lines    = market_lines
                    st.session_state.foreign_str     = foreign_str
                    st.session_state.volume_str      = volume_str
                    st.session_state.news_str        = news_str

                except Exception as e:
                    st.error(f"❌ 오류 발생: {e}")

        if st.session_state.analysis_result:
            st.markdown(f"### 📊 시장 현황 *(분석시각: {st.session_state.analysis_time})*")
            for line in st.session_state.market_lines:
                st.markdown(f"- {line}")
            st.markdown("---")
            st.markdown("### 💹 주요 종목 수급")
            st.markdown(st.session_state.foreign_str)
            st.markdown("### 🔥 주요 종목 거래량")
            st.markdown(st.session_state.volume_str)
            st.markdown("---")
            with st.expander("📰 수집된 실시간 뉴스"):
                st.markdown(st.session_state.news_str)
            st.markdown("---")
            st.markdown("### 🤖 AI 분석 결과")
            st.markdown(st.session_state.analysis_result)

    # ==========================================
    # TAB 2: 종목 검색 분석
    # ==========================================
    with tab2:
        st.markdown("### 🔍 종목 검색 상세 분석")
        st.caption("종목코드(예: 066570) 또는 종목명(예: LG전자)으로 검색")

        col1, col2 = st.columns([3, 1])
        with col1:
            search_input = st.text_input(
                "종목 검색",
                placeholder="종목코드(066570) 또는 종목명(LG전자)",
                label_visibility="collapsed"
            )
        with col2:
            search_btn = st.button("🔍 분석", use_container_width=True)

        if search_btn and search_input:
            query = search_input.strip()

            with st.spinner(f"🔍 '{query}' 검색 중..."):
                try:
                    kis_token = get_kis_token()
                    code = ""
                    종목명 = ""

                    # 한글/영문 이름 검색
                    if not query.replace(".", "").isdigit():
                        if kis_token:
                            code, 종목명 = search_stock_code(kis_token, query)
                            if not code:
                                st.error(f"❌ '{query}' 종목을 찾을 수 없습니다.")
                                st.stop()
                        else:
                            st.error("❌ KIS 토큰 발급 실패. 코드로 검색해주세요.")
                            st.stop()
                    else:
                        code = query.replace(".KS", "").replace(".KQ", "").zfill(6)

                    # KS/KQ 자동 판별
                    yf_code, hist = find_yf_code(code)
                    if yf_code is None:
                        st.error(f"❌ '{code}' 시세 데이터를 찾을 수 없습니다.")
                        st.stop()

                    # 종목명 없으면 yfinance에서
                    if not 종목명:
                        t_info = yf.Ticker(yf_code).info
                        종목명 = t_info.get("longName") or t_info.get("shortName") or code

                    현재가 = float(hist["Close"].iloc[-1])
                    전일가 = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else 현재가
                    등락률 = ((현재가 - 전일가) / 전일가) * 100
                    거래량 = int(hist["Volume"].iloc[-1])

                    hist_1y = yf.Ticker(yf_code).history(period="1y").dropna()
                    고가52  = float(hist_1y["High"].max()) if not hist_1y.empty else 현재가
                    저가52  = float(hist_1y["Low"].min())  if not hist_1y.empty else 현재가

                    detail = get_kis_stock_detail(kis_token, code) if kis_token else {}
                    per    = detail.get("per", "N/A")
                    pbr    = detail.get("pbr", "N/A")

                    ind = calc_indicators(yf_code)

                    investor_data  = get_kis_stock_investor(kis_token, code) if kis_token else []
                    investor_lines = []
                    for o in investor_data:
                        date = o.get("stck_bsop_date", "")
                        dstr = f"{date[4:6]}/{date[6:8]}" if len(date) == 8 else date
                        frgn = o.get("frgn_ntby_qty", "0")
                        inst = o.get("orgn_ntby_qty", "0")
                        prsn = o.get("prsn_ntby_qty", "0")
                        investor_lines.append(
                            f"- [{dstr}] 외국인 {int(frgn):+,}주 | 기관 {int(inst):+,}주 | 개인 {int(prsn):+,}주"
                        )
                    investor_str = "\n".join(investor_lines) if investor_lines else "수급 데이터 없음"

                    stock_news = get_stock_related_news(code, 종목명)

                    # ===== 화면 출력 =====
                    sign  = "▲" if 등락률 > 0 else "▼"
                    color = "🔴" if 등락률 < 0 else "🟢"
                    st.markdown(f"## {color} {종목명} ({yf_code})")

                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        st.metric("현재가", f"{현재가:,.0f}원", f"{sign}{abs(등락률):.2f}%")
                    with col_b:
                        st.metric("거래량", f"{거래량:,}주")
                    with col_c:
                        st.metric("52주 최고", f"{고가52:,.0f}원")

                    st.markdown("---")
                    st.markdown("#### 📋 기본 정보")
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown(f"**PER:** {per}")
                    with col2:
                        st.markdown(f"**PBR:** {pbr}")
                    with col3:
                        st.markdown(f"**52주 저가:** {저가52:,.0f}원")

                    if ind:
                        st.markdown("#### 📊 기술적 지표")
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            rsi_color = "🔴" if ind['rsi'] >= 70 else "🟢" if ind['rsi'] <= 30 else "🟡"
                            st.markdown(f"**RSI**\n{rsi_color} {ind['rsi']}")
                        with col2:
                            st.markdown(f"**MACD**\n{ind['macd']}")
                        with col3:
                            st.markdown(f"**볼린저밴드**\n{ind['bb']}")
                        with col4:
                            stoch_color = "🔴" if ind['stoch_k'] >= 80 else "🟢" if ind['stoch_k'] <= 20 else "🟡"
                            st.markdown(f"**스토캐스틱**\n{stoch_color} {ind['stoch_k']}")
                        st.markdown(
                            f"📉 이동평균: MA5 {ind['ma5']:,.0f} | MA20 {ind['ma20']:,.0f}" +
                            (f" | MA60 {ind['ma60']:,.0f}" if ind['ma60'] else "")
                        )

                    st.markdown("#### 👥 투자자별 매매동향 (최근 5일)")
                    st.markdown(investor_str)

                    with st.expander("📰 관련 뉴스"):
                        st.markdown(stock_news)

                    st.markdown("---")
                    if st.button("🤖 AI 종합 분석 시작", use_container_width=True, key="search_ai_btn"):
                        with st.spinner("🤖 AI 분석 중..."):
                            ind_full = f"""
RSI: {ind['rsi']} ({'과매수' if ind['rsi']>=70 else '과매도' if ind['rsi']<=30 else '중립'})
MACD: {ind['macd']} (MACD값 {ind['macd_val']}, Signal {ind['signal_val']})
볼린저밴드: {ind['bb']} (상단 {ind['bb_upper']:,.0f} / 하단 {ind['bb_lower']:,.0f})
스토캐스틱: {ind['stoch_k']} ({'과매수' if ind['stoch_k']>=80 else '과매도' if ind['stoch_k']<=20 else '중립'})
이동평균: MA5 {ind['ma5']:,.0f} / MA20 {ind['ma20']:,.0f}""" if ind else "지표 계산 불가"

                            genai.configure(api_key=MY_API_KEY)
                            model = genai.GenerativeModel('gemini-2.5-flash')
                            prompt_search = f"""
당신은 대한민국 주식시장에서 30년 이상 활동한 최고 수익률의 전문 트레이더입니다.

[분석 종목]
종목명: {종목명} ({yf_code})
현재가: {현재가:,.0f}원 ({sign}{abs(등락률):.2f}%)
거래량: {거래량:,}주
PER: {per} / PBR: {pbr}
52주 최고: {고가52:,.0f}원 / 52주 최저: {저가52:,.0f}원

[기술적 지표]
{ind_full}

[투자자별 매매동향 최근 5일]
{investor_str}

[관련 뉴스]
{stock_news}

[현재 시장 상황]
{market_context}

아래 형식으로 모바일에서 읽기 편하게 분석해주세요:

1. 📊 종합 진단
- 현재 주가 위치 분석
- 기술적 지표 종합 해석
- 수급 흐름 분석
- 뉴스/이슈 영향

2. 📈 매매 전략
- 진단: 매수 / 관망 / 매도
- 매수 적정가
- 1차 목표가 / 2차 목표가
- 손절가
- 투자 기간: 단기/중기/장기

3. ⚠️ 리스크 요인

4. 💬 전문가 한마디
"""
                            response = generate_with_retry(model, prompt_search)
                            st.markdown("### 🤖 AI 종합 분석")
                            st.markdown(response.text)

                except Exception as e:
                    st.error(f"❌ 오류 발생: {e}")
