import streamlit as st
import yfinance as yf
import google.generativeai as genai
from datetime import datetime, timedelta
import pytz
import pandas as pd # ⚠️ 새로 추가된 라이브러리 (requirements.txt에 추가 필요)

# ==========================================
# 0. 나만의 비밀 설정 (Private 저장소 필수)
# ==========================================
MY_ID = "jgyunam"       # 원하는 아이디로 변경하세요
MY_PW = "1q2w3e4r5t"        # 원하는 비밀번호로 변경하세요
MY_API_KEY = "AIzaSyCKVXJkXDKHJPhjTXHenrsoT9EcXHZyDP8" # 여기에 발급받은 Gemini API 키를 붙여넣으세요!

# ==========================================
# 1. 상태 및 시간 설정
# ==========================================
kst = pytz.timezone('Asia/Seoul')
now = datetime.now(kst)
current_time = now.strftime("%H:%M")
is_weekend = now.weekday() >= 5
market_close_time = now.replace(hour=15, minute=30, second=0, microsecond=0)

if is_weekend:
    target_period = "다음 주 월요일"
    status_msg = "주말 휴장 중입니다. 다음 주를 준비합니다."
elif now > market_close_time:
    target_period = "내일(다음 거래일)"
    status_msg = f"오늘 장 마감 ({current_time}) 내일을 준비합니다."
else:
    target_period = "오늘 실시간"
    status_msg = f"현재 장 운영 중 ({current_time}) 실시간 대응!"

st.set_page_config(page_title="나만의 주식 비서", page_icon="📱", layout="centered")

# Session State 초기화 (로그인 상태, 포트폴리오)
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'api_key' not in st.session_state:
    st.session_state.api_key = ""
if 'portfolio' not in st.session_state:
    # 빈 포트폴리오 데이터프레임 생성
    st.session_state.portfolio = pd.DataFrame(columns=["종목명", "보유수량", "평단가"])

korean_stocks = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "한미반도체": "042700.KS",
    "현대차": "005380.KS", "NAVER": "035420.KS", "LG에너지솔루션": "373220.KS", "셀트리온": "068270.KS"
}

# ==========================================
# 2. 로그인 화면 처리
# ==========================================
if not st.session_state.logged_in:
    st.markdown("<h2 style='text-align: center;'>🔒 로그인</h2>", unsafe_allow_html=True)
    
    with st.container():
        input_id = st.text_input("아이디")
        input_pw = st.text_input("비밀번호", type="password")
        
        if st.button("로그인", use_container_width=True):
            if input_id == MY_ID and input_pw == MY_PW:
                st.session_state.logged_in = True
                st.session_state.api_key = MY_API_KEY
                st.success("로그인 성공!")
                st.rerun() # 화면 새로고침
            else:
                st.error("아이디 또는 비밀번호가 틀렸습니다.")

# ==========================================
# 3. 메인 화면 (로그인 성공 시)
# ==========================================
else:
    st.markdown(f"<h3 style='text-align: center;'>📱 AI {target_period} 픽 & 내 자산 분석</h3>", unsafe_allow_html=True)
    st.info(status_msg, icon="⏰")
    
    # --- 포트폴리오 입력 영역 ---
    with st.expander("💼 내 주식 포트폴리오 입력/수정", expanded=True):
        st.caption("현재 보유 중인 종목의 수량과 평균단가를 입력하세요.")
        
        # st.data_editor를 사용하여 엑셀처럼 쉽게 수정 가능하게 만듭니다.
        edited_df = st.data_editor(
            st.session_state.portfolio,
            num_rows="dynamic", # 행 추가/삭제 가능
            column_config={
                "종목명": st.column_config.SelectboxColumn("종목명", options=list(korean_stocks.keys()), required=True),
                "보유수량": st.column_config.NumberColumn("보유수량(주)", min_value=1, step=1),
                "평단가": st.column_config.NumberColumn("평단가(원)", min_value=1, step=100)
            },
            use_container_width=True
        )
        # 수정된 표를 저장
        st.session_state.portfolio = edited_df

    st.markdown("---")

    # --- AI 분석 실행 영역 ---
    if st.button(f"🚀 내 주식 진단 및 {target_period} 추천 받기", use_container_width=True):
        with st.spinner("AI가 내 자산과 시장 데이터를 분석 중입니다..."):
            try:
                # 1. 시장 데이터 및 내 주식 현재가 수집
                market_data_str = ""
                my_portfolio_str = ""
                
                for name, ticker in korean_stocks.items():
                    df = yf.download(ticker, period="5d", progress=False)
                    if not df.empty:
                        if isinstance(df.columns[0], tuple): df.columns = [col[0] for col in df.columns]
                        current_price = int(df['Close'].iloc[-1])
                        change = ((df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
                        market_data_str += f"- {name}: {current_price:,}원 ({change:+.2f}%)\n"
                        
                        # 내 포트폴리오에 있는 종목이면 수익률 계산해서 문자열에 추가
                        my_stock_row = st.session_state.portfolio[st.session_state.portfolio['종목명'] == name]
                        if not my_stock_row.empty:
                            avg_price = my_stock_row.iloc[0]['평단가']
                            quantity = my_stock_row.iloc[0]['보유수량']
                            profit_rate = ((current_price - avg_price) / avg_price) * 100
                            my_portfolio_str += f"- {name}: {quantity}주 보유 (평단가 {avg_price:,}원 -> 현재가 {current_price:,}원 / 수익률: {profit_rate:+.2f}%)\n"

                # 내 주식이 하나도 입력되지 않았을 경우의 예외 처리
                if not my_portfolio_str:
                    my_portfolio_str = "현재 보유 중인 주식이 없습니다."

                # 2. AI 프롬프트 (Gemini 2.5 Flash)
                genai.configure(api_key=st.session_state.api_key)
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                prompt = f"""
                당신은 냉철하고 분석적인 한국 주식 전문가입니다. 현재 시각은 {now.strftime('%Y-%m-%d %H:%M')}이며, {status_msg}
                
                [시장 주요 종목 현재 상태]
                {market_data_str}
                
                [사용자의 현재 보유 주식 및 수익률]
                {my_portfolio_str}

                위 데이터를 바탕으로 사용자에게 스마트폰 화면에 최적화된 리포트를 작성해 주세요. 가로로 긴 표는 절대 쓰지 마세요.

                아래의 양식을 엄격하게 지켜서 출력하세요.

                ### 💼 내 포트폴리오 진단
                (사용자가 보유한 주식 각각에 대해 유지/분할매도/분할매수 중 명확한 행동 지침과 이유를 2줄 이내로 제시하세요. 보유 주식이 없다면 이 섹션은 '보유 주식이 없습니다'라고만 적으세요.)
                * **[종목명] (수익률):** [대응 전략] - [핵심 사유]

                ---
                ### 🎯 {target_period} 신규 추천 픽
                (보유 주식 외에, 현재 시장 상황에서 가장 투자하기 좋은 2개 종목을 추천하세요.)
                1. **[종목명]:** * ⏰ **대응 시간:** [시간대]
                   * 💡 **추천 사유:** [사유 요약]
                2. **[종목명]:** * ⏰ **대응 시간:** [시간대]
                   * 💡 **추천 사유:** [사유 요약]
                
                ---
                **👨‍💼 전문가의 총평**
                [사용자의 포트폴리오 상태와 전체 시장을 아우르는 뼈때리는 조언 2줄]
                """

                response = model.generate_content(prompt)
                st.markdown(response.text)

            except Exception as e:
                st.error(f"분석 중 오류 발생: {e}")
