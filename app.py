import streamlit as st
import yfinance as yf
import google.generativeai as genai
from datetime import datetime
import pytz
import pandas as pd
import json
from github import Github

# ==========================================
# 0. 설정
# ==========================================
MY_ID = "jgyunam"
MY_PW = "1234"

MY_API_KEY   = st.secrets["GEMINI_API_KEY"]
GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
REPO_NAME    = st.secrets["REPO_NAME"]
FILE_PATH    = "portfolio.json"

# ==========================================
# 1. 깃허브 JSON 파일 읽기/쓰기 함수
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
# 2. 자동 저장 함수
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
# 3. 메인 페이지 로직
# ==========================================
st.set_page_config(page_title="AI 주식 비서 PRO", page_icon="📈", layout="centered")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

# --- 로그인 화면 ---
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

# --- 메인 앱 화면 ---
else:
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    target_period = "내일" if now.hour >= 16 else "오늘"

    st.markdown(f"<h3 style='text-align: center;'>📱 {target_period} 맞춤형 리포트</h3>", unsafe_allow_html=True)

    # 포트폴리오 관리 영역
    with st.expander("💼 내 종목 관리", expanded=False):
        st.data_editor(
            st.session_state.portfolio,
            num_rows="dynamic",
            use_container_width=True,
            key="portfolio_editor",
            on_change=auto_save  # ← 수정할 때마다 자동 저장
        )
        st.caption("✏️ 수정 후 자동 저장됩니다")

    st.markdown("---")

    # 분석 버튼 및 로직
    if st.button("🚀 AI 자산 진단 시작", use_container_width=True):
        with st.spinner("📡 시장 데이터 수집 중..."):
            try:
                # ==========================================
                # [1단계] 시장 데이터 수집
                # ==========================================
                tickers = {
                    "코스피": "^KS11",
                    "코스닥": "^KQ11",
                    "달러/원": "KRW=X",
                    "나스닥": "^IXIC",
                    "S&P500": "^GSPC",
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

                # ==========================================
                # [2단계] 포트폴리오 현재가 조회
                # ==========================================
                portfolio = st.session_state.portfolio.copy()
                portfolio_lines = []

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

                    portfolio_lines.append(
                        f"- {종목명}: 현재가 {현재가:,.0f}원 | 평단 {평단가:,.0f}원 | "
                        f"{sign}{abs(손익률):.1f}% | 평가손익 {손익:+,.0f}원"
                    )

                my_portfolio_str = "\n".join(portfolio_lines) if portfolio_lines else "포트폴리오 없음"

                # ==========================================
                # [3단계] Gemini AI 분석
                # ==========================================
                genai.configure(api_key=MY_API_KEY)
                model = genai.GenerativeModel('gemini-2.5-flash')

                prompt = f"""
한국 주식 전문가로서 다음 데이터를 분석해 주세요.

[시장 정보]
{market_data_str}

[내 자산]
{my_portfolio_str}

1. 내 종목 진단
   - 종목별 유지/매도/추가매수 의견
   - 매수 시점 (목표 매수가 또는 조건)
   - 매도 시점 (목표 매도가 또는 조건)

2. {target_period} 신규 추천 종목 3개
   - 종목명 및 추천 이유
   - 매수 시점 (목표 매수가 또는 조건)
   - 매도 시점 (목표 매도가 또는 조건)

3. 전문가 총평

모바일에서 읽기 편하게 세로 리스트 형식으로 작성하세요.
"""
                response = model.generate_content(prompt)
                result_text = response.text

                # ==========================================
                # [4단계] 결과 출력
                # ==========================================
                st.markdown("### 📊 시장 현황")
                for line in market_lines:
                    st.markdown(f"- {line}")

                st.markdown("---")
                st.markdown("### 🤖 AI 분석 결과")
                st.markdown(result_text)

            except Exception as e:
                st.error(f"❌ 오류 발생: {e}")
