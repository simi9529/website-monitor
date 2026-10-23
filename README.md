# Website monitor

동아대 게시판, 유튜브 커뮤니티와 로그인 필요한 이화이언
<https://ewhaian.com/life/66>의 새 글을 이메일로 알립니다.

## 실행 설정

기존 `.github/workflows/dongaupdate.yml`이 5분마다 `dongaupdate.py`를 실행합니다.
GitHub 저장소의 **Settings → Secrets and variables → Actions → Secrets**에
다음 값을 등록하세요. 클라우드 환경의 변수는 GitHub Actions로 자동 복사되지 않습니다.

| 이름 | 값 |
| --- | --- |
| `FROM_EMAIL` | 알림을 보내는 Gmail 주소 |
| `TO_EMAIL` | 알림을 받을 이메일 주소 |
| `APP_PASSWORD` | 발신 Gmail 계정의 16자리 앱 비밀번호 |
| `EWHA_ID` | 해당 게시판을 열람할 수 있는 이화이언 계정 아이디 |
| `EWHA_PW` | 이화이언 계정 비밀번호 |

이화이언 계정은 아이디/비밀번호로 로그인합니다. 로그인 결과의 토큰은 실행 중
메모리에서만 사용하며 파일에 저장하지 않습니다. 계정 정보가 없거나 로그인에
실패하면 이화이언 확인만 건너뛰고 기존 사이트 모니터링을 계속합니다.
비밀번호나 토큰을 코드·로그·채팅에 넣지 마세요.

이화이언은 **첫 실행에 최신 글 번호만 기록**하고, 이후 실행부터 새 글을 알립니다.
한 회차 사이에 여러 글이 올라오면 **모든 새 글의 제목과 링크를 메일 한 통에**
오래된 글부터 담아 발송합니다. 새 글이 2개면 메일에 두 링크가 모두 포함됩니다.
발송에 실패하면 상태를 갱신하지 않고 다음 실행에 모두 재시도합니다.
`titles.json`에 마지막으로 알린 글 번호를 저장하므로
기존 Actions의 상태 커밋 단계가 필요합니다. 작업 간격은 GitHub 스케줄 상황에 따라
5분보다 길어질 수 있습니다.

로컬에서는 Python 3.11 가상환경에 의존성을 설치한 뒤, 위 환경변수를 안전하게
설정하고 저장소 디렉터리에서 실행하세요. 이 명령은 실제 이메일을 보낼 수 있습니다.

```sh
python -m pip install -r requirements.txt
python dongaupdate.py
```

실제 로그인과 메일 발송을 확인하려면 같은 환경변수를 설정한 뒤 다음 명령을
실행하세요. **현재 최신 글의 제목과 링크를 담은 실제 메일 한 통을 발송**합니다.
메일 서버가 수신을 수락한 뒤, 아직 모니터링 시작 기준이 없다면 해당 글 번호를
기록합니다. 기존 모니터링 기준이 있으면 미발송 글을 건너뛰지 않도록 유지합니다.

```sh
python dongaupdate.py --send-latest-ewhaian
```

이 클라우드에서 Gmail SMTP 연결이 되지 않으면 GitHub Actions 실행 환경에서
시험 발송할 수 있습니다. 변경사항을 GitHub에 반영하고 위 다섯 값을 Actions
Secrets에 등록한 뒤, **Actions → Site Monitor → Run workflow**에서
`send_latest_ewhaian`을 체크해 실행하세요. 체크하지 않은 수동 실행과 예약 실행은
평소처럼 모든 사이트를 확인합니다. 클라우드에 저장한 인증 정보는 Actions로
자동 전달되지 않습니다. Actions에서의 실제 SMTP 연결·메일 발송 성공 여부는
해당 실행 로그로 확인해야 합니다.

이화이언은 사이트가 사용하는 로그인·목록 조회 API를 사용하므로 브라우저 설치가
필요하지 않습니다. 사이트 API가 변경되거나 계정의 열람 권한이 없으면 로그를
확인하세요. CAPTCHA나 추가 인증을 우회하지 않습니다.

외부 계정·메일 발송 없이 기능을 검증하려면:

```sh
python -m unittest discover -s tests -v
```
