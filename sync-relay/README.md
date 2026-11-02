# 기기 간 알림 확인 동기화

한 기기에서 알림을 누르면 다른 기기의 같은 알림을 닫는 선택 기능입니다.
기존 알림은 동기화 설정 없이도 계속 작동합니다. 화면에서 밀어 지운 동작은 동기화하지 않습니다.

## 배포

1. Cloudflare 계정에서 Workers & Pages → Create application → Worker를 만듭니다.
   `worker.mjs` 내용을 Worker 코드로 배포합니다. 별도 npm 의존성은 없습니다.
2. Workers KV 네임스페이스를 만들고 Worker의 KV Binding을 **`ACK_STORE`**로 연결합니다.
3. 충분히 긴 무작위 비밀값을 생성해 Worker의 Secret **`SYNC_API_KEY`**로 등록합니다.
   코드·공개 Variables·채팅에는 비밀값을 넣지 않습니다.
4. GitHub 저장소 Settings → Secrets and variables → Actions에서:
   - **Variables**: `PUSH_SYNC_URL` = 배포된 Worker의 HTTPS 주소(경로 없이)
   - **Secrets**: `PUSH_SYNC_API_KEY` = Worker의 `SYNC_API_KEY`와 같은 값
5. 폰과 태블릿 모두 알림 페이지를 다시 열어 새 서비스 워커를 적용합니다.
   `test_push`로 새 시험 알림을 보내 두 기기에서 받은 후 한쪽에서 누릅니다.

Wrangler CLI를 사용할 경우 `wrangler.toml`의 KV ID를 생성한 네임스페이스 ID로
바꾸고 `wrangler secret put SYNC_API_KEY`, `wrangler deploy`를 실행합니다.
Wrangler 로그인·배포 계정 연결은 별도로 필요합니다.

## 동작과 한계

- 기존 GitHub Secret의 VAPID 비밀키·기기 구독 정보는 GitHub에 그대로 둡니다.
  GitHub에서 이미 암호화하고 서명한 닫기 패킷만 Worker로 보냅니다.
- 알림마다 기기별 무작위 확인 토큰을 발급합니다. 해당 알림을 받은 기기만
  그 알림의 확인 상태를 변경할 수 있습니다. API 키나 다른 기기의 구독 정보는 폰에 보내지 않습니다.
- Worker는 확인 상태와 전송 패킷을 비공개 KV에 최대 48시간 저장합니다.
  패킷의 VAPID 서명·푸시 TTL은 약 24시간이므로 오래된 알림의 동기화는 보장하지 않습니다.
- 등록 API는 서버용 비밀키가 있어야 호출할 수 있습니다. 확인 API는 기기별 토큰을
  POST 본문으로 받습니다. 상태와 토큰을 공개 저장소나 URL 쿼리에 저장하지 않습니다.
- 동기화 서버 장애 시 기존 알림을 계속 보냅니다. 이 경우 해당 알림은 동기화되지 않습니다.
- 크롬의 userVisibleOnly 제약 때문에 닫기 신호는 같은 태그의 알림을 무음으로 갱신한 뒤 닫습니다.
  Android 버전에 따라 확인됨 표시가 잠깐 보이거나 시스템 표시가 남을 수 있습니다.
  실제 두 기기 동작은 배포 후 확인해야 합니다.
- 다른 기기가 오프라인·절전 상태면 닫기 신호가 늦게 도착할 수 있습니다.
  KV의 지역 간 반영 지연도 있어 즉각적인 동기화를 보장하지 않습니다.
- 링크 열기는 동기화 요청과 병렬로 실행합니다. 서버 오류 때문에 링크 열기를 막지 않습니다.

검증:

```sh
python -m unittest discover -s tests -v
node --test tests/test_push_worker.cjs tests/test_sync_relay.mjs
```
