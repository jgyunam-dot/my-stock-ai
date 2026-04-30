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
MY_ID = st.secrets["MY_ID"]
MY_PW = st.secrets["MY_PW"]

MY_API_KEY      = st.secrets["GEMINI_API_KEY"]
GITHUB_TOKEN    = st.secrets["GITHUB_TOKEN"]
REPO_NAME       = st.secrets["REPO_NAME"]
KIS_APP_KEY     = st.secrets["KIS_APP_KEY"]
KIS_APP_SECRET  = st.secrets["KIS_APP_SECRET"]
FILE_PATH       = "portfolio.json"
KIS_BASE_URL    = "https://openapi.koreainvestment.com:9443"

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
# 2. KIS - 주요 종목 수급 조회
# ==========================================
def get_kis_foreign_buying(token):
    major_stocks = [
        ("삼성전자", "005930"),
        ("SK하이닉스", "000660"),
        ("현대차", "005380"),
        ("POSCO홀딩스", "005490"),
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
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code
            }
            res = requests.get(url, headers=headers, params=params, timeout=5)
            data = res.json()
            output = data.get("output", [])

            item = None
            for o in output:
                if o.get("frgn_ntby_qty", "") != "":
                    item = o
                    break

            if item:
                frgn = item.get("frgn_ntby_qty", "0")
                inst = item.get("orgn_ntby_qty", "0")
                date = item.get("stck_bsop_date", "")
                date_str = f"{date[4:6]}/{date[6:8]}" if len(date) == 8 else ""
                lines.append(
                    f"- {name}({code}) [{date_str}기준]: "
                    f"외국인 {int(frgn):+,}주 | 기관 {int(inst):+,}주"
                )
        except:
            continue
    return "\n".join(lines) if lines else "수급 데이터 없음"

# ==========================================
# 3. 거래량 - yfinance로 주요 종목 조회
# ==========================================
def get_volume_rank():
    major_stocks = [
        ("삼성전자", "005930.KS"),
        ("SK하이닉스", "000660.KS"),
        ("현대차", "005380.KS"),
        ("카카오", "035720.KS"),
        ("NAVER", "035420.KS"),
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
            elif len(data) == 1:
                vol  = int(data["Volume"].iloc[-1])
                curr = data["Close"].iloc[-1]
                lines.append(f"- {name}: 거래량 {vol:,}주 | {curr:,.0f}원")
        except:
            continue
    return "\n".join(lines) if lines else "거래량 데이터 없음"

# ==========================================
# 4. 기술적 지표 계산
# ==========================================
def calc_indicators(ticker_code):
    try:
        data = yf.Ticker(ticker_code).history(period="3mo").dropna()
        if len(data) < 26:
            return None
        close = data["Close"]

        delta = close.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rs    = gain / loss
        rsi   = round((100 - (100 / (1 + rs))).iloc[-1], 1)

        ema12  = close.ewm(span=12).mean()
        ema26  = close.ewm(span=26).mean()
        macd   = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        macd_cross = "골든크로스 ▲" if macd.iloc[-1] > signal.iloc[-1] else "데드크로스 ▼"

        ma20  = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        upper = ma20 + 2 * std20
        lower = ma20 - 2 * std20
        bb_pos = "상단 근접" if close.iloc[-1] > upper.iloc[-1] * 0.98 else \
                 "하단 근접" if close.iloc[-1] < lower.iloc[-1] * 1.02 else "중간"

        return {"rsi": rsi, "macd": macd_cross, "bb": bb_pos}
    except:
        return None

# ==========================================
# 5. 깃허브 JSON 파일 읽기/쓰기
# ==========================================
def load_github_json():
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        file_content = repo.get_contents(FILE_PATH)
        data = json.loads(file_content.decoded_content.decode())
        return pd.DataFrame(data)
    except:
        return pd.DataFrame(columns=["종목명", "보유수량", "평단가"])

def save_github_json(df):
    try:
        g = Github(GITHUB_TOKEN)
        repo = g.get_repo(REPO_NAME)
        data_str = df.to_json(orient='records', force_ascii=False)
        try:
            contents = repo.get_contents(FILE_PATH)
            repo.update_file(
                path=contents.path,
                message="Update portfolio data",
                content=data_str,
                sha=contents.sha
            )
        except:
            repo.create_file(
                path=FILE_PATH,
                message="Initial portfolio data",
                content=data_str
            )
        return True
    except Exception as e:
        st.error(f"❌ 저장 중 오류 발생: {e}")
        return False

# ==========================================
# 6. 자동 저장
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
    result = save_github_json(df)
    if result:
        st.session_state.portfolio = df

# ==========================================
# 7. 장 상태 판단
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
# 8. Google 뉴스 RSS
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
# 9. 429 재시도
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
# 10. 메인 페이지
# ==========================================
st.set_page_config(page_title="AI 주식 비서 PRO", page_icon="📈", layout="centered")

# session_state 초기화
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'analysis_result' not in st.session_state:  # ← 분석 결과 저장용
    st.session_state.analysis_result = None
if 'analysis_time' not in st.session_state:    # ← 분석 시각 저장용
    st.session_state.analysis_time = None
if 'market_lines' not in st.session_state:
    st.session_state.market_lines = None
if 'foreign_str' not in st.session_state:
    st.session_state.foreign_str = None
if 'volume_str' not in st.session_state:
    st.session_state.volume_str = None
if 'news_str' not in st.session_state:
    st.session_state.news_str = None

# --- 로그인 ---
if not st.session_state.logged_in:
    st.markdown("<h2 style='text-align: center;'>🔒 로그인</h2>", unsafe_allow_html=True)
    id_input = st.text_input("아이디")
    pw_input = st.text_input("비밀번호", type="password")
    if st.button("로그인", use_container_width=True):
        if id_input == MY_ID and pw_input == MY_PW:
            st.session_state.logged_in = True
            st.session_state.portfolio = load_github_json()
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 틀렸습니다.")

# --- 메인 ---
else:
    now, target_period, market_context = get_market_context()
    st.markdown(f"<h3 style='text-align: center;'>📱 {target_period} 맞춤형 리포트</h3>", unsafe_allow_html=True)

    with st.expander("💼 내 종목 관리", expanded=False):
        st.data_editor(
            st.session_state.portfolio,
            num_rows="dynamic",
            use_container_width=True,
            key="portfolio_editor",
            on_change=auto_save
        )
        st.caption("✏️ 수정 후 자동 저장됩니다")

    st.markdown("---")

    if st.button("🚀 AI 자산 진단 시작", use_container_width=True):
        with st.spinner("📡 시장 데이터 수집 중..."):
            try:
                # [1단계] 시장 지수
                tickers = {
                    "코스피": "^KS11",
                    "코스닥": "^KQ11",
                    "달러/원": "KRW=X",
                    "나스닥":  "^IXIC",
                    "S&P500":  "^GSPC",
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
                            curr = data["Close"].iloc[-1]
                            market_lines.append(f"{name}: {curr:,.2f} (전일비 없음)")
                        else:
                            curr = t.fast_info.get("last_price", None)
                            if curr:
                                market_lines.append(f"{name}: {curr:,.2f} (실시간)")
                            else:
                                market_lines.append(f"{name}: 데이터 없음")
                    except Exception as e:
                        market_lines.append(f"{name}: 조회 실패 ({e})")
                market_data_str = "\n".join(market_lines)

                # [2단계] KIS 수급 + 거래량
                with st.spinner("📊 수급/거래량 데이터 수집 중..."):
                    kis_token = get_kis_token()
                    foreign_str = get_kis_foreign_buying(kis_token) if kis_token else "KIS 토큰 발급 실패"
                    volume_str  = get_volume_rank()

                # [3단계] 뉴스
                with st.spinner("📰 실시간 뉴스 수집 중..."):
                    news_str = get_stock_news()

                # [4단계] 포트폴리오 현재가 + 기술지표
                portfolio = st.session_state.portfolio.copy()
                portfolio_lines = []
                my_stock_codes = portfolio["종목명"].astype(str).str.strip().tolist()
                my_stock_codes_str = ", ".join(my_stock_codes) if my_stock_codes else "없음"

                for _, row in portfolio.iterrows():
                    종목명 = str(row["종목명"]).strip()
                    수량   = float(row["보유수량"])
                    평단가 = float(row["평단가"])
                    try:
                        info = yf.Ticker(종목명).history(period="5d").dropna()
                        현재가 = info["Close"].iloc[-1] if not info.empty else 평단가
                    except:
                        현재가 = 평단가

                    총매입 = 평단가 * 수량
                    총평가 = 현재가 * 수량
                    손익   = 총평가 - 총매입
                    손익률 = ((현재가 - 평단가) / 평단가) * 100
                    sign   = "▲" if 손익률 > 0 else "▼"
                    ind = calc_indicators(종목명)
                    ind_str = f"RSI {ind['rsi']} | MACD {ind['macd']} | BB {ind['bb']}" if ind else "지표 계산 불가"
                    portfolio_lines.append(
                        f"- {종목명}: 현재가 {현재가:,.0f}원 | 평단 {평단가:,.0f}원 | "
                        f"{sign}{abs(손익률):.1f}% | 평가손익 {손익:+,.0f}원\n"
                        f"  기술지표: {ind_str}"
                    )
                my_portfolio_str = "\n".join(portfolio_lines) if portfolio_lines else "포트폴리오 없음"

                # [5단계] AI 추천 종목
                genai.configure(api_key=MY_API_KEY)
                model = genai.GenerativeModel('gemini-2.5-flash')

                with st.spinner("🤖 AI 추천 종목 선정 중..."):
                    prompt_ticker = f"""
당신은 대한민국 주식시장에서 30년 이상 활동한 최고 수익률의 전문 트레이더입니다.

[현재 시장 상황]
{market_data_str}

[주요 종목 수급]
{foreign_str}

[주요 종목 거래량]
{volume_str}

[오늘의 실시간 뉴스]
{news_str}

[분석 시점]
{market_context}

[보유 종목 - 절대 추천 금지]
{my_stock_codes_str}

위 데이터를 종합해서 조건을 충족하는 종목만 추천하세요:
- 보유 종목과 완전히 다른 종목
- 외국인 또는 기관 순매수가 활발한 종목 우선
- 거래량 증가 + 뉴스 모멘텀이 있는 종목
- {target_period} 시장 흐름에 맞는 종목

아래 JSON 형식으로만 출력하세요. 다른 말은 절대 하지 마세요:
[
  {{"name": "종목명", "code": "종목코드.KS또는.KQ", "reason": "추천이유"}},
  {{"name": "종목명", "code": "종목코드.KS또는.KQ", "reason": "추천이유"}},
  {{"name": "종목명", "code": "종목코드.KS또는.KQ", "reason": "추천이유"}}
]
"""
                    response_ticker = generate_with_retry(model, prompt_ticker)
                    json_str = re.search(r'\[.*\]', response_ticker.text, re.DOTALL).group()
                    recommend_list = json.loads(json_str)

                # [6단계] 추천 종목 현재가 + 기술지표
                recommend_lines = []
                for item in recommend_list:
                    try:
                        info = yf.Ticker(item["code"]).history(period="5d").dropna()
                        현재가 = info["Close"].iloc[-1] if not info.empty else None
                        if 현재가:
                            매수가  = 현재가 * 0.97
                            목표가1 = 현재가 * 1.10
                            목표가2 = 현재가 * 1.20
                            손절가  = 현재가 * 0.93
                            ind = calc_indicators(item["code"])
                            ind_str = f"RSI {ind['rsi']} | MACD {ind['macd']} | BB {ind['bb']}" if ind else "지표 계산 불가"
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
기술적 분석(RSI, MACD, 볼린저밴드), 기본적 분석(PER, PBR),
섹터 로테이션, 외국인/기관 수급 분석까지 모두 활용합니다.

[분석 시점]
{market_context}

[시장 정보]
{market_data_str}

[주요 종목 수급]
{foreign_str}

[주요 종목 거래량]
{volume_str}

[오늘의 실시간 뉴스]
{news_str}

[내 보유 자산 현황 + 기술지표]
{my_portfolio_str}

[신규 추천 종목 실제 현재가 + 기술지표]
{recommend_str}

아래 3가지를 모바일에서 읽기 편하게 세로 리스트로 작성하세요.

---

1. 📊 내 종목 진단
각 종목마다:
- 종목명
- 현재 상태 (수익/손실 %)
- 기술지표 해석 (RSI 과매수/과매도, MACD 방향, BB 위치)
- 진단: 유지 / 추가매수 / 일부매도 / 전량매도
- 근거: 수급+뉴스+기술지표 종합 2~3줄
- 매수 시점: 구체적 가격
- 매도 시점: 목표가 및 손절가

---

2. 🔥 {target_period} 신규 추천 종목 3개
각 종목마다:
- 종목명 (코드)
- 현재가 (위 데이터 그대로, 절대 임의로 만들지 말 것)
- 기술지표 해석
- 추천 근거: 수급+뉴스+모멘텀 3~4줄
- 매수 시점
- 1차 목표가 / 2차 목표가
- 손절가
- 투자 기간: 단기 / 중기 / 장기

---

3. 💬 전문가 총평
- 수급 + 뉴스 기반 시장 흐름 평가
- {target_period} 핵심 투자 전략 한 줄
- 리스크 경고
"""
                    response = generate_with_retry(model, prompt)
                    result_text = response.text

                # ✅ 분석 결과 session_state에 저장 (백그라운드 복귀 시 유지)
                kst = pytz.timezone('Asia/Seoul')
                st.session_state.analysis_result = result_text
                st.session_state.analysis_time   = datetime.now(kst).strftime("%m/%d %H:%M")
                st.session_state.market_lines    = market_lines
                st.session_state.foreign_str     = foreign_str
                st.session_state.volume_str      = volume_str
                st.session_state.news_str        = news_str

            except Exception as e:
                st.error(f"❌ 오류 발생: {e}")

    # ✅ 저장된 분석 결과 항상 표시 (앱 복귀 시에도 유지)
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
