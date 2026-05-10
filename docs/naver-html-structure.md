# 네이버 검색 결과 HTML 구조 (실측 기반)

**기준 fixture**: `tests/fixtures/naver/*.html` (2026-05-05 수집).
**수집 방식**: GET https://search.naver.com/search.naver?query=KEYWORD (브라우저 헤더 + brotli decoding).

## 1. 최상위 결과 박스

각 결과 항목 (또는 블록)의 외곽 컨테이너:

```
div.api_subject_bx.desktop_mode
```

- `api_subject_bx` 는 네이버 표준 (오랜 기간 유지된 클래스명).
- `desktop_mode` 는 데스크탑 결과 박스 식별용. 모바일/광고 일부 박스에는 없음.
- 같은 박스에 해시 클래스 (예: `gfibyuTWlNnE9GG1RzEo`) 가 같이 붙는데 빌드마다 변경 가능 → 무시.

광고/시스템 박스는 `desktop_mode` 가 없으므로 자동 제외:
- `div.api_subject_bx` 만 있는 것: 광고/Npay/오류 박스.

## 2. 박스 종류 분류 (h2 자손 기반)

각 `desktop_mode + api_subject_bx` 박스 안의 `<h2>` 자손 유무로 종류 결정.

| h2 자손 | 박스 종류 | 처리 책임 |
|---------|-----------|-----------|
| 없음 + 메인 a[href] 있음 | **AB 통합 검색 결과 항목** (1개 박스 = 1개 결과) | M4.7 |
| `h2.fds-aib-header-title-text: AI 브리핑` | AI 브리핑 | skip |
| `h2.sds-comps-text: 이미지` | 이미지 박스 | skip |
| `h2.sds-comps-text: <스마트블록명>` (예: `올리브영샴푸순위`) | 스마트블록 | M4.8 |
| `h2.sds-comps-text: '<키워드>' 인기글` 또는 `<카테고리> 인기글` | 인기글 블록 | M4.9 |
| `h2.sds-comps-text: '<키워드>' 관련 브랜드 콘텐츠` | 브랜드 콘텐츠 | M4.8/M4.9 |
| `h2.title_area: <키워드>관련 광고` | 광고 (어차피 desktop_mode 없어서 미선택) | skip |
| `h2.nqAxdu9h: 네이버 가격비교 / 네이버플러스 스토어` | 쇼핑 | skip |

핵심 단순 규칙: **h2 자손이 있으면 AB 외 다른 블록 → _parse_ab_list 는 skip**.

## 3. AB 항목의 메인 URL 추출

각 AB 박스 안에서 가장 텍스트가 긴 `<a href>` 가 메인 결과.
- 카페 글: `https://cafe.naver.com/<slug>/<post_id>?art=...`
- 블로그 글: `https://blog.naver.com/<id>/<post_id>` (또는 web view)
- 외부 사이트: 외부 도메인 그대로.

쿼리스트링 (`?art=`, `?source=` 등) 은 path 비교 시 무시.

## 4. 항목 타입 분류 (cafe/blog/web)

메인 URL 도메인으로 분류:
- `cafe.naver.com` → cafe
- `blog.naver.com` → blog
- 그 외 → web

## 5. 순위 매기기 (실측 ab_cafe_top.html 기준)

검색어 `등드름해초필링`, target=`cafe.naver.com/pusanmommy/1445556`:

| idx | 박스 | 도메인 | 종류 |
|-----|------|--------|------|
| 1 | pusanmommy/1445556 | cafe | **TARGET** (cafe_slot_rank=1) |
| 2 | directwedding/8875029 | cafe | |
| 3 | wkqdbsxo14/2176804 | cafe | |
| 4 | b00k2012/1367973 | cafe | |
| 5 | blog.naver.com/khsoo1007 | blog | |
| 6 | blog.naver.com/facemartin | blog | |
| ... | ... | ... | |

→ `integrated_rank=1`, `cafe_slot_rank=1`, `parser_confidence=0.9`.

## 6. URL 매칭 규칙

쿼리/fragment 무시, netloc + path 일치:
```python
urlparse(a).netloc == urlparse(b).netloc
urlparse(a).path.rstrip("/") == urlparse(b).path.rstrip("/")
```

## 7. 주의사항 — fixture 인코딩

**네이버는 brotli (`Accept-Encoding: br`) 응답을 기본으로 보냄.**
- requests 라이브러리는 brotli decode 위해 `brotli` 패키지 필요 (없으면 raw bytes → utf-8 decode 실패 → fixture 깨짐).
- requirements.txt 에 `brotli==1.1.0` 포함됨 (T-M4.7 진행 중 추가).

## 8. 스마트블록 (M4.8 — 실측 mixed_blocks.html 기준)

**식별**: `desktop_mode + api_subject_bx` 박스에 `<h2>` 자손이 있고, h2 텍스트가 아래 skip 패턴 중 어떤 것도 포함하지 않는 경우.

**Skip 패턴** (스마트블록 아님):
- `인기글` → 인기글 (M4.9 책임)
- `관련 브랜드 콘텐츠` → 브랜드 광고
- `이미지` → 이미지 박스
- `AI 브리핑` → AI 브리핑
- `네이버 클립` → 클립
- `네이버 가격비교`, `네이버플러스 스토어` → 쇼핑

**스마트블록명** = `h2.sds-comps-text` 의 텍스트 그대로 (예: `올리브영샴푸순위`, `탈모샴푸 순위`).

**박스 안 결과 항목 추출**:
- 박스 내부 모든 `a[href]` 중:
  - http(s) 만, `keep.naver.com` 제외, path 가 `/` 또는 빈 path 인 출처 root URL 제외
  - 같은 (netloc, path) 는 dedup
- 위에서 아래 순서대로 idx 1..N 부여
- target_url 매칭하면 → `smart_block_name` 채우고 True 리턴

**실측 mixed_blocks.html (검색어=샴푸순위) 기준**:
| 박스 | h2 | 종류 | 처리 |
|------|----|----|------|
| [1] | (없음) | AB 항목 (브런치) | M4.7 |
| [2] | 올리브영샴푸순위 | 스마트블록 | M4.8 ← 본 task |
| [3] | 탈모샴푸 순위 | 스마트블록 | M4.8 |
| [4] | '샴푸순위' 인기글 | 인기글 | M4.9 |
| [5] | '샴푸순위' 관련 브랜드 콘텐츠 | 브랜드 광고 | skip |
| [6] | 이미지 | 이미지 | skip |

box[2] 항목들 (예시):
1. `blog.naver.com/comprehensive5189/223816275254`
2. `in.naver.com/layeonparkgogo/contents/internal/946448`
3. `blog.naver.com/liil2903/224204441107`

## 9. 인기글 (M4.9 — 실측 popular_cafe.html 기준)

**식별**: `desktop_mode + api_subject_bx` 박스에 `<h2>` 자손이 있고, h2 텍스트에 `인기글` 포함.

**박스 안 항목 = 출처 + 본문 페어**:
- 출처 a (path = `/<slug>` 만): 카페/블로그 메인 페이지
- 본문 a (path = `/<slug>/<post_id>`, post_id 가 숫자): 실제 글

**순위 매기기 규칙** (사장님 컨벤션, plan.md):
1. 박스 안 본문 a (post_id 있는 URL) 만 카운트
2. **출처 (slug) 별 dedup** — 같은 출처 의 첫 본문만 카운트
3. 위에서 아래 순서로 idx 1..N
4. target 매칭 시 그 idx = `cafe_slot_rank` (M 컬럼)
5. `exposure_area = POPULAR`, `parser_confidence = 0.85`

**실측 popular_cafe.html (검색어=트러블크림) box[2] '패션·미용 인기글'**:
| idx | 출처 | 본문 |
|-----|------|------|
| 1 | juhee960123 | blog.naver.com/juhee960123/224253557960 |
| 2 | uos3778 | blog.naver.com/uos3778/224205565950 |
| 3 | **cosmania** | **cafe.naver.com/cosmania/38373348** ← TARGET |
| 4 | tonyforlife | blog.naver.com/tonyforlife/224120739869 |
| ... | ... | ... |

→ target=cosmania/38373348 매칭 시 `cafe_slot_rank=3` ✓ (plan.md "3등" 정합)

⚠️ 같은 출처 의 다른 본문 (cosmania/38349398, cosmania/38340172) 은 idx 카운트에서 제외 — 이미 cosmania 가 idx 3 으로 매겨졌음.

## 10. 지식인 (M4.9 — 실측 smart_block.html 기준)

**식별**: 검색 결과 페이지에 `kin.naver.com` 도메인 링크가 있고, 그 중 target_url 매칭.

**실측 분포**:
- `ab_cafe_top.html`, `popular_cafe.html`, `mixed_blocks.html`, `no_match.html`: kin.naver.com 0개
- `smart_block.html` (두피관리법): kin.naver.com 24개 (개별 결과 항목으로 노출)

⚠️ 별도 "지식iN 박스" 가 검색 결과에 분리되지 않음. 결과 항목의 출처 가 "네이버 지식iN" 인 경우 그 a[href] 가 kin.naver.com 도메인. 즉 AB 통합 리스트의 한 결과로 등장.

**규칙**:
- 페이지 어디든 `kin.naver.com` 링크 중 target_url 매칭 → `in_jisikin = True`
- target 이 cafe.naver.com / blog.naver.com URL 인 경우 → 일반적으로 False (spec O 컬럼은 사장님 글이 지식인에도 노출되는 드문 케이스만 'O')
- 단순 fallback: 페이지에 kin.naver.com 0개 → False 즉시 리턴

## 11. 후속 task 참조

- M4.10 block_order — 페이지 위→아래로 모든 desktop_mode + api_subject_bx 박스 순서대로 종류 list 작성.
