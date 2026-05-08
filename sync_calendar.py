import os
import json
from datetime import datetime, timedelta
from notion_client import Client
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# --- 환경 변수 로드 ---
NOTION_API_KEY = os.environ["NOTION_API_KEY"]
NOTION_DB_ID = os.environ["NOTION_DB_ID"]
GOOGLE_CALENDAR_ID = os.environ["GOOGLE_CALENDAR_ID"]
GOOGLE_CREDENTIALS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]

notion = Client(auth=NOTION_API_KEY)

# --- 구글 캘린더 인증 설정 ---
SCOPES = ['https://www.googleapis.com/auth/calendar']
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
service = build('calendar', 'v3', credentials=creds)

def format_gcal_date(date_str, is_end=False):
    """Notion 날짜 형식을 구글 캘린더 형식으로 변환"""
    if 'T' in date_str: # 시간이 포함된 경우
        return {'dateTime': date_str}
    else:               # 시간 없이 날짜만 있는 종일 일정의 경우
        if is_end:
            # 구글 캘린더의 종일 일정 종료일은 하루를 더해줘야 완벽하게 반영됨
            dt = datetime.fromisoformat(date_str) + timedelta(days=1)
            return {'date': dt.strftime('%Y-%m-%d')}
        return {'date': date_str}

def sync_to_calendar():
    print("--- Notion -> Google Calendar 동기화 시작 ---")
    
    # 1. Notion 데이터 가져오기 (가장 최근 수정된 100개)
    results = notion.databases.query(
        database_id=NOTION_DB_ID,
        sorts=[{"timestamp": "last_edited_time", "direction": "descending"}]
    ).get("results", [])

    for page in results:
        props = page["properties"]
        page_id = page["id"]

        # 2. 제목 추출 (어떤 속성 이름이든 Title 타입이면 가져옴)
        title = "제목 없음"
        for key, value in props.items():
            if value.get("type") == "title" and value.get("title"):
                title = value["title"][0]["text"]["content"]
                break

        # 3. '기간' 속성에서 날짜 추출 (이전에 만든 그 열 사용)
        date_prop = props.get("기간", {}).get("date")
        if not date_prop:
            continue # 기간이 입력되지 않은 일정은 패스
            
        start_str = date_prop.get("start")
        end_str = date_prop.get("end") if date_prop.get("end") else start_str

        # 구글 캘린더용 이벤트 바디 구성
        event_body = {
            'summary': title,
            'description': f"Notion Page ID: {page_id}\n이 일정은 깃허브 액션으로 자동 동기화되었습니다.",
            'start': format_gcal_date(start_str),
            'end': format_gcal_date(end_str, is_end=True),
        }

        # 4. 캘린더에서 이미 등록된 일정인지 Page ID로 검색
        events_result = service.events().list(
            calendarId=GOOGLE_CALENDAR_ID,
            q=page_id, 
            singleEvents=True
        ).execute()
        
        events = events_result.get('items', [])

        # 5. 일정 생성 또는 업데이트
        try:
            if events:
                event_id = events[0]['id']
                service.events().update(calendarId=GOOGLE_CALENDAR_ID, eventId=event_id, body=event_body).execute()
                print(f"🔄 업데이트됨: {title}")
            else:
                service.events().insert(calendarId=GOOGLE_CALENDAR_ID, body=event_body).execute()
                print(f"✅ 새로 생성됨: {title}")
        except Exception as e:
            print(f"❌ 동기화 실패 ({title}): {e}")

if __name__ == "__main__":
    sync_to_calendar()
