import streamlit as st
import yfinance as yf
import google.generativeai as genai
from datetime import datetime, timedelta
import pytz
import pandas as pd
import json
from github import Github # ⚠️ PyGithub 라이브러리 필요

# ==========================================
# 0. 나만의 비밀 설정 (Private 저장소이므로 직접 입력)
# ==========================================
MY_ID = "jgyunam"
MY_PW = "1234"
MY_API_KEY = "AIzaSyCKVXJkXDKHJPhjTXHenrsoT9EcXHZyDP8" # 내 제미나이 키
GITHUB_TOKEN = "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" # 방금 발급받은 깃허브 토큰
REPO_NAME = "jgyunam-dot/my-stock-ai" # 예: "jeon/my-stock-ai"
FILE_PATH = "portfolio.json" # 저장될 파일 이름

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
        # 파일이 없거나 오류 시 빈 데이터프레임 반환
        return pd.DataFrame(columns=["종목명", "보유수량", "평단가"])

def save_github_json(df):
    g = Github(GITHUB_TOKEN)
    repo = g.get_repo(REPO_NAME)
    data_str = df.to_json(orient='records', force_ascii=False)
    
    try:
        # 기존 파일 업데이트
        contents = repo.get_contents(FILE_PATH)
        repo.update_contents(contents.path, "Update portfolio", data_str, contents.sha)
    except:
        # 파일이 없으면 새로 생성
        repo.create_contents(FILE_PATH, "Create portfolio", data_str)

# ==========================================
# 2. 메인 페이지 로직
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
            st.session_state.portfolio = load_github_json() # 로그인 시점에 깃허브에서 로드
            st.rerun()
        else:
            st.error("정보가 틀렸습니다.")

# --- 메인 앱 화면 ---
else:
    kst = pytz.timezone('Asia/Seoul')
    now = datetime.now(kst)
    target_period = "내일" if now.hour >= 16 else "오늘"
    
    st.markdown(f"<h3 style='text-align: center;'>📱 {target_period} 맞춤형 리포트</h3>", unsafe_allow_html=True)

    # 포트폴리오 관리 영역
    with st.expander("💼 내 종목 관리 (JSON 저장)", expanded=False):
        edited_df = st.data_editor(st.session_state.portfolio, num_rows="dynamic", use_container_width=True)
        if st.button("💾 깃허브에 JSON 데이터 저장", use_container_width=True):
            save_github_json(edited_df)
            st.session_state.portfolio = edited_df
            st.success("깃허브 저장소에 portfolio.json이 업데이트되었습니다!")

    st.markdown("---")

    # 분석 버튼 및 로직
    if st.button("🚀 AI 자산 진단 시작", use_container_width=True):
        with st.spinner("AI 분석 중..."):
            try:
                # 데이터 수집 (생략: 이전 코드와 동일)
                # ... [이전과 동일한 yfinance 데이터 수집 로직] ...
                
                # AI 모델 호출 (알려주신 모델 사용)
                genai.configure(api_key=MY_API_KEY)
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                # 프롬프트 및 결과 출력 (생략: 이전 코드와 동일)
                # ...
                st.write("AI 분석 결과가 여기에 표시됩니다.")
                
            except Exception as e:
                st.error(f"오류 발생: {e}")
