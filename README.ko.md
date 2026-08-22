# line-api-skill

**LINE API를 추측하지 말고, 찾아보세요.**

LINE Platform 문서 전체를 검색 가능한 데이터베이스로 만드는
[Agent Skill](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview).
AI 어시스턴트가 기억이 아니라 명세를 근거로 답하게 됩니다.

<p>
  <img src="https://img.shields.io/badge/endpoints-121-success?style=flat-square" alt="121 endpoints">
  <img src="https://img.shields.io/badge/fields-1584-blue?style=flat-square" alt="1584 fields">
  <img src="https://img.shields.io/badge/dataset-3675%20rows-orange?style=flat-square" alt="3675 rows">
  <img src="https://img.shields.io/badge/platforms-8-9cf?style=flat-square" alt="8 platforms">
  <img src="https://img.shields.io/badge/python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/dependencies-0-brightgreen?style=flat-square" alt="zero dependencies">
</p>

```
121개 엔드포인트 · 1,584개 요청/응답 필드 · 295개 응답 필드
233개 오류 코드 · 247개 webhook 필드 · 136개 Flex 컴포넌트 · 44개 URL 스킴
58개 버전에 걸친 35개 LIFF API · 80개 모바일 SDK 타입 · 92개 공식 FAQ
```

[English](README.md) · [繁體中文](README.zh-TW.md) · [日本語](README.ja.md) · 한국어

---

## 이 스킬이 푸는 문제

LINE API는 작은 실수의 대가를 추적하기 어려운 방식으로 돌려줍니다.

`chatBarText`는 14자 제한. 캐러셀 각 칼럼의 `text`는 120자까지 —— 다만 썸네일이나
제목을 넣는 순간 60자로 줄어듭니다. 리치 메뉴 이미지는 `api.line.me`가 아니라
`api-data.line.me`로 업로드합니다. replyToken은 한 번만, 1분 안에만 유효합니다.
같은 캐러셀 안의 bubble은 너비가 모두 같아야 합니다.

어느 것도 추측으로 맞힐 수 없고, 기억에 의존하는 어시스턴트는 자신 있게 틀립니다.
이 스킬은 먼저 찾아보게 만듭니다.

## 빠른 시작

```bash
git clone https://github.com/Moksa1123/line-api-skill
cd line-api-skill
python tools/install-skill.py claude-code --global
```

그다음은 평소 쓰는 말로 요청하면 됩니다:

```
당신:        주문 조회에 Flex 카드로 답하는 LINE 봇을 만들어줘

어시스턴트:  (엔드포인트·Flex 구조·필드 제한을 찾아보고,
              코드를 작성한 뒤 보내기 전에 JSON을 오프라인 검증)
```

## 설치

```bash
python tools/install-skill.py --list                   # 지원 플랫폼 보기
python tools/install-skill.py claude-code --global
python tools/install-skill.py cursor                   # 현재 프로젝트에 설치
python tools/install-skill.py claude-ai --to ./build    # 업로드용 zip 생성
```

8개 플랫폼 —— Claude Code, Claude.ai, Cursor, Codex CLI, Gemini CLI,
Devin Desktop(구 Windsurf), GitHub Copilot, Continue. 플랫폼이 스킬을 읽는 방식에 따라
세 가지 형태로 설치합니다: 디렉터리 전체, 단일 규칙 파일로 평탄화, 웹 업로드용 zip.
업그레이드 시 이전 버전이 남긴 파일을 지웁니다 —— 작년의 틀린 데이터를 올해의 맞는
데이터 옆에 남겨두는 설치 도구는 없느니만 못하기 때문입니다.

## 사용법

보통은 도구를 직접 실행할 일이 없습니다. 스킬이 어시스턴트에게 절차를 가르칩니다:

```
1. 먼저 찾기       search.py     엔드포인트, 필드, 제한, enum, 오류, FAQ
2. JSON 작성       (어시스턴트)   방금 찾은 구조 그대로, 추측하지 않음
3. 오프라인 검증   validate.py   타입, 필수, 오타, enum, 상한, 폐기된 요소
4. 그다음 전송     lineapi.py    올바른 호스트, 올바른 헤더
```

직접 실행할 수도 있습니다:

```bash
python scripts/search.py "carousel"                  # 검색 도메인 자동 판별
python scripts/search.py "get bot info" --domain response
python scripts/validate.py message.json --as push
python scripts/signature.py verify --secret <s> --body-file b.json --signature <sig>
python scripts/lineapi.py info
```

검증기는 문제 위치를 경로로 정확히 짚어줍니다:

```
❌ $.contents.body.layout               필수 속성 layout 누락
❌ $.contents.body.contents[0].weight   'extra-bold'는 유효하지 않음 — regular, bold 사용
⚠️  $.template.columns                  칼럼별 action 개수가 일치하지 않음
```

### 이미 작성된 코드 점검

기존 구현을 리뷰어에 넘기면 같은 데이터셋으로 대조합니다 —— 이 엔드포인트가
실제로 존재하는지, 호스트가 맞는지, 서명을 원본 body로 계산하고 상수 시간으로
비교하는지, 메시지 JSON이 유효한지, 그 API가 아직 살아 있는지.

```bash
python scripts/review.py ./src
python scripts/review.py app.py --min-severity error   # 반드시 고쳐야 할 것만
python scripts/review.py ./src --format json           # CI 연동용
```

```
❌ [signature-body] app.py:14   재직렬화한 JSON으로 서명을 계산함
   → 원본 바이트를 사용 (Flask: request.get_data() | Express: express.raw())
❌ [wrong-host]      app.py:29   /v2/bot/message/{}/content 는 api-data.line.me
⚠️  [message-json]    app.py:21   알 수 없는 속성 'quickreply' (quickReply 아닌가요?)
```

9개 규칙, 각각 수정 방법과 공식 문서 링크가 함께 나옵니다. 문제가 없으면 아무것도
보고하지 않습니다 —— 이 저장소의 예제에 대해 0건임을 테스트가 보장합니다.

## 다루는 범위

| 영역 | 찾을 수 있는 것 |
|---|---|
| Messaging API | 97개 엔드포인트, 레이트 리밋, 재시도 키, 발송 한도, 통계 |
| 메시지 객체 | 11가지 타입, 퀵 리플라이, 4가지 템플릿, 9가지 action |
| Flex Message | 컨테이너, 9개 컴포넌트, 모든 속성, 용량 제한 |
| 리치 메뉴 | 객체 구조, 이미지 사양, 별칭, 사용자별 연결 |
| Webhook | 20개 이벤트, 타입이 있는 247개 필드, 서명 검증 |
| LINE Login | OAuth 2.0 + OIDC, 스코프, ID 토큰 검증 |
| LIFF | 35개 API, 도입 버전, 트리 셰이킹 모듈 |
| LINE MINI App | 인증/미인증 차이, 서비스 메시지, 인앱 결제 |
| URL 스킴 | 44개 스킴과, 자주 걸리는 세 가지 플랫폼 제약 |
| 모바일 SDK | iOS / Android 80개 타입, 공식 레퍼런스 링크 포함 |

여기에 LINE 공식 용어 57개, FAQ 92개, 정리된 문제 해결 목록, 그리고 종료된 기능 목록
(LINE Notify는 2025-03-31 종료)까지 포함되어 있어 어시스턴트가 죽은 API를 권하지 않습니다.

## 도구

| 도구 | 하는 일 |
|---|---|
| `search.py` | 25개 도메인 BM25 검색. 중국어 질의는 영어 용어로 자동 확장 |
| `validate.py` | 메시지 / Flex 오프라인 검증: 타입, 필수, 오타, enum, 상한 |
| `signature.py` | webhook 서명, 채널 액세스 토큰(순수 Python RS256 JWT 구현 포함) |
| `lineapi.py` | 의존성 없는 Messaging API 클라이언트. 호스트를 자동 분기 |
| `review.py` | 기존 코드 점검: 종료된 API, 잘못된 호스트, 서명 처리, 엔드포인트 오타, 메시지 JSON |
| `test_line.py` | 오프라인 45개 + 라이브 6개 테스트 |

## 데이터를 만드는 방법

```
https://developers.line.biz/llms.txt        github.com/line/line-openapi
        ↓ tools/fetch_sources.py                    ↓
231개 공식 페이지 (대부분 .md 버전 있음)        10개 OpenAPI 명세
        ↓ tools/build_dataset.py
line-api/data/*.csv    ← 교차 검증: 문서의 엔드포인트 ⊇ OpenAPI의 엔드포인트
```

네 개의 독립된 검사. 모두 실제로 오류를 잡아낸 적이 있습니다:

| 검사 | 확인하는 것 |
|---|---|
| `test_line.py` | 데이터 무결성, 검색, 검증기, 서명, JWT |
| `audit_coverage.py` | 문서에 있는 필드가 모두 데이터셋에 들어갔는지 |
| `check_links.py` | 모든 문서 URL이 유효한지 (SPA의 가짜 200도 탐지) |
| `check_docs.py` | README의 숫자가 실제 데이터와 일치하는지 |

수집한 페이지는 `.docs-cache/`에 있으며 **git에서 제외되고 공개되지 않습니다**
—— 그 내용은 LY Corporation의 것입니다. 이 저장소가 공개하는 것은 거기서 도출한
데이터셋과 직접 작성한 설명뿐입니다.

최신 문서로 갱신하려면:

```bash
python tools/fetch_sources.py
python tools/build_dataset.py
python tools/audit_coverage.py
python tools/check_links.py --md
python tools/check_docs.py
python line-api/scripts/test_line.py
```

## 라이선스

이 저장소의 코드는 MIT.

LINE, LINE Messaging API, LIFF, LINE MINI App은 LY Corporation의 상표입니다.
이 프로젝트는 LY Corporation과 관련이 없으며, 데이터셋은 공개 문서와 공개 OpenAPI
명세를 정리한 것입니다.
