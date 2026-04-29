import streamlit as st
import yfinance as yf
import google.generativeai as genai
from datetime import datetime, timedelta
import pytz

# ==========================================
# 1. 한국 시간(KST) 및 장 상태 로직
# ==========================================
kst = pytz.timezone('Asia/Seoul')
now = datetime.now(kst)
current_time = now.strftime("%H:%M")
is_weekend = now.weekday() >= 5 # 5: 토요일, 6: 일요일

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

# ==========================================
# 2. 페이지 설정 (모바일 최적화: layout="centered")
# ==========================================
# wide 대신 centered를 사용하여 모바일 화면 비율에 예쁘게 맞춥니다.
st.set_page_config(page_title="모바일 주식 AI", page_icon="📱", layout="centered")

# 모바일 친화적인 중앙 정렬 헤더
st.markdown(f"<h3 style='text-align: center;'>📱 AI {target_period} 픽</h3>", unsafe_allow_html=True)
st.info(status_msg, icon="⏰")

if 'api_key' not in st.session_state:
    st.session_state.api_key = ""

# ==========================================
# 3. 설정 메뉴 (모바일은 사이드바 대신 Expander 사용)
# ==========================================
# 모바일에서는 사이드바가 숨겨지므로, 화면 본문에 아코디언(접기/펴기) 형태로 배치합니다.
with st.expander("⚙️ 설정 (API 키 입력)", expanded=not st.session_state.api_key):
    temp_api_key = st.text_input("Gemini API Key를 입력하세요", type="password", value=st.session_state.api_key)
    
    # 모바일에서 누르기 편하도록 꽉 차는 버튼(use_container_width=True) 적용
    if st.button("🔑 키 저장", use_container_width=True):
        st.session_state.api_key = temp_api_key.strip()
        st.success("저장 완료! 이제 창을 접고 아래 버튼을 눌러주세요.")

st.markdown("---")

# ==========================================
# 4. 데이터 수집 및 AI 분석
# ==========================================
korean_stocks = {
    "삼성전자": "005930.KS", "SK하이닉스": "000660.KS", "한미반도체": "042700.KS",
    "현대차": "005380.KS", "NAVER": "035420.KS", "LG에너지솔루션": "373220.KS", "셀트리온": "068270.KS"
}

if not st.session_state.api_key:
    st.warning("위 설정 메뉴를 눌러 API 키를 먼저 입력해주세요.")
else:
    # 엄지손가락으로 누르기 쉬운 대형 버튼
    if st.button(f"🚀 {target_period} 추천 받기", use_container_width=True):
        with st.spinner("AI가 데이터를 분석 중입니다..."):
            try:
                market_data_str = ""
                for name, ticker in korean_stocks.items():
                    df = yf.download(ticker, period="5d", progress=False)
                    if not df.empty:
                        if isinstance(df.columns[0], tuple): df.columns = [col[0] for col in df.columns]
                        price = int(df['Close'].iloc[-1])
                        change = ((df['Close'].iloc[-1] - df['Close'].iloc[-2]) / df['Close'].iloc[-2]) * 100
                        market_data_str += f"- {name}: {price:,}원 ({change:+.2f}%)\n"

                # ⭐️ 지정해주신 모델명 적용
                genai.configure(api_key=st.session_state.api_key)
                model = genai.GenerativeModel('gemini-2.5-flash')
                
                # 모바일에서는 표(Table) 대신 세로형 카드(Card) 디자인으로 출력하도록 프롬프트 수정
                prompt = f"""
                당신은 한국 주식 전문가입니다. 현재 시각은 {now.strftime('%Y-%m-%d %H:%M')}이며, {status_msg}
                분석 대상 데이터:
                {market_data_str}

                위 데이터를 참고하여 {target_period} 투자하기 좋은 국내 주식 3개를 선정해주세요.
                스마트폰 화면에서 가독성이 좋도록 가로로 긴 표를 절대 사용하지 말고, 아래와 같은 세로형 텍스트 형식으로 깔끔하게 출력하세요.

                ### 🎯 추천 1: [종목명]
                * **⏰ 대응 시간:** [시간대 입력]
                * **💡 추천 전략:** [매수/홀딩/관망 및 핵심 사유 2줄 요약]
                
                (위 형식을 3개 종목 모두 반복)

                ---
                **👨‍💼 전문가의 한마디**
                [전체 시장 분위기와 주의사항을 모바일에서 읽기 편하게 2~3줄로 짧게 요약]
                """

                response = model.generate_content(prompt)
                st.markdown(response.text)

            except Exception as e:
                st.error(f"분석 중 오류 발생: {e}")