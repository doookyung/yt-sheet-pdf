# 🎼 yt-sheet-pdf — 유튜브 악보 영상을 PDF로

유튜브 연주/레슨 영상 중에 화면에 악보(탭)가 같이 나오는 영상 있죠?
그 영상 링크만 주면, **악보가 넘어갈 때마다 자동으로 캡쳐해서 PDF 한 장으로** 만들어 줍니다.

- 재생 커서(파란 하이라이트 바)가 움직이는 건 무시하고, **악보 줄이 실제로 바뀔 때만** 캡쳐
- 같은 악보가 다시 나오는 반복 구간은 자동으로 빼줌
- 인트로/연주 장면처럼 악보가 아닌 화면도 자동으로 빼줌
- 결과: 낱장 PNG + A4 비율로 정리된 PDF

---

## 0. 준비물 (딱 두 가지)

| 필요한 것 | 확인 방법 |
|---|---|
| **Mac / Windows / Linux** 아무거나 | Windows는 "터미널" 대신 **PowerShell**을 씁니다 → 아래 "Windows 사용자" 참고 |
| **Python 3.10 이상** | 아래 1단계에서 확인 |

> 터미널이 처음이라면: Mac에서 `⌘ + Space` → `터미널` 입력 → Enter 하면 검은 창이 열립니다. 아래 명령어들은 전부 그 창에 **복사 → 붙여넣기 → Enter** 하면 됩니다.

---

## 1. Python 있는지 확인

터미널에 이렇게 입력하고 Enter:

```bash
python3 --version
```

- `Python 3.12.x` 처럼 **3.10 이상**이 나오면 OK → 2단계로
- `command not found` 가 나오거나 3.9 이하면 → https://www.python.org/downloads/ 에서 최신 버전 설치 후 터미널을 **껐다 다시 켜고** 다시 확인

---

## 2. 프로그램 받기 + 설치 (최초 1회만)

터미널에 아래 한 줄을 통째로 복사해서 붙여넣고 Enter:

```bash
git clone https://github.com/doookyung/yt-sheet-pdf.git && cd yt-sheet-pdf && ./setup.sh
```

1~2분 정도 걸리고, 마지막에 `설치 완료!` 가 뜨면 끝입니다.
(`git` 이 없다고 나오면 `xcode-select --install` 을 실행해서 설치한 뒤 다시 시도하세요.)

이제 내 홈 폴더에 `yt-sheet-pdf` 폴더가 생겼습니다.

---

## 3. 사용하기

### ① 폴더로 이동

터미널을 새로 열었다면 항상 먼저 이걸 입력:

```bash
cd ~/yt-sheet-pdf
```

### ② 유튜브 링크 넣고 실행

```bash
./sheet2pdf "https://www.youtube.com/watch?v=XXXXXXXX"
```

> 링크는 **꼭 큰따옴표 `"` 로 감싸 주세요.** (링크에 `&` 같은 문자가 있으면 따옴표 없이는 오류가 납니다.)

### ③ 악보 영역 드래그

잠시 후 영상의 한 장면이 담긴 창이 뜹니다.

1. **악보가 있는 부분**을 마우스로 드래그해서 네모를 그리고
2. **Enter** 를 누르세요

> 💡 창이 안 보이면 **Dock에 있는 Python(뱀) 아이콘**을 클릭하세요. 터미널 뒤에 숨어 있는 경우가 많습니다.
> 💡 잘못 그렸으면 그냥 다시 드래그하면 됩니다. 취소는 `c`.

### ④ 기다리기

터미널에 `[page 1] 01m52s` 같은 줄이 하나씩 올라오면서 진행됩니다.
5분짜리 영상이면 보통 30초~1분 정도 걸립니다.

### ⑤ 결과 확인

끝나면 `~/yt-sheet-pdf/output/` 폴더에 저장됩니다. 바로 열어 보려면:

```bash
open output
```

```
output/
├── <영상 제목>.pdf          ← 이걸 인쇄하거나 아이패드로 보내면 됩니다
└── pages/
    ├── page_001_01m52s.png  ← 캡쳐된 낱장 (파일 이름에 영상 시각이 있어요)
    ├── page_002_02m02s.png
    └── ...
```

---

## 4. 자주 생기는 상황

### 🔹 악보 배경이 검정/어두운 색이에요
기본은 "밝은 배경 = 악보" 라고 판단해서 어두운 화면을 빼버립니다. 다크 테마 악보라면 이 필터를 끄세요:

```bash
./sheet2pdf "링크" --min-bright 0
```

### 🔹 엉뚱한 장면이 몇 장 섞여 들어갔어요
`output/pages/` 폴더에서 **잘못된 PNG를 삭제**한 뒤, PDF만 다시 만들면 됩니다:

```bash
./sheet2pdf --from-images output/pages --name 곡이름.pdf
```

### 🔹 페이지가 너무 많이 잡혀요 (커서 움직임까지 잡힘)
감도를 낮추세요 (숫자를 키움):

```bash
./sheet2pdf "링크" --threshold 0.12
```

### 🔹 페이지가 넘어갔는데 안 잡혀요
감도를 높이세요 (숫자를 줄임):

```bash
./sheet2pdf "링크" --threshold 0.03
```

### 🔹 영상 앞뒤에 악보 없는 부분이 길어요
분석 구간을 지정하세요:

```bash
./sheet2pdf "링크" --start 1:30 --end 6:00
```

### 🔹 같은 채널 영상을 여러 개 할 건데 매번 드래그하기 귀찮아요
한 번 드래그하면 터미널에 `[region] --region 0,0,1280,340` 처럼 좌표가 찍힙니다. 그걸 그대로 붙이면 창 없이 바로 실행됩니다:

```bash
./sheet2pdf "링크" --region 0,0,1280,340
```

### 🔹 PDF 한 장에 악보 하나씩만 넣고 싶어요

```bash
./sheet2pdf "링크" --per-page 1
```

### 🔹 이미 컴퓨터에 있는 영상 파일로 하고 싶어요
링크 자리에 파일 경로를 넣으면 됩니다:

```bash
./sheet2pdf ~/Downloads/lesson.mp4
```

### 🔹 다운로드가 안 돼요 / 유튜브 오류가 나요
유튜브가 자주 바뀌어서 다운로더를 업데이트해야 할 때가 있습니다:

```bash
.venv/bin/pip install -U yt-dlp
```

---

## 5. 전체 옵션 표 (참고용)

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--region x,y,w,h` / `full` | (드래그 선택) | 악보 영역. 원본 영상 픽셀 기준 |
| `--pick-at 2:00` | 구간 중간 | 드래그 선택 창에 띄울 장면의 시각 |
| `--start`, `--end` | 전체 | 분석 구간 (`90`, `1:30`, `1m30s` 다 됨) |
| `--interval` | 0.5 | 몇 초마다 검사할지. 페이지가 아주 빨리 넘어가면 0.25 |
| `--threshold` | 0.06 | 페이지 전환으로 볼 변화 비율 (0~1) |
| `--settle` | 2 | 전환 뒤 이만큼 연속 안정되면 캡쳐 (전환 애니메이션 중 캡쳐 방지) |
| `--dedup` | 0.02 | 이전 페이지와 이 비율 미만으로 다르면 중복 처리. `0`이면 끔 |
| `--min-bright` | 0.5 | 밝은 픽셀 비율이 이보다 낮으면 악보 아님으로 제외. 다크 테마면 `0` |
| `--per-page` | 자동 | PDF 한 장에 넣을 캡쳐 수 |
| `--name` | 영상 제목 | PDF 파일 이름 |
| `-o` | `output` | 결과 저장 폴더 |
| `--max-height` | 1080 | 다운로드 최대 해상도 |
| `--keep-video` | | 다운로드한 영상 파일을 지우지 않음 |
| `--debug` | | 프레임별 변화량 출력 (threshold 튜닝할 때) |

---

## Windows 사용자

Windows에도 터미널이 있습니다. 이름이 **PowerShell**이에요.

1. 시작 메뉴 클릭 → `PowerShell` 입력 → 나오는 파란 창(Windows PowerShell) 클릭해서 열기
2. Python이 없다면 https://www.python.org/downloads/ 에서 설치 — **설치 화면에서 "Add python.exe to PATH" 체크박스 꼭 체크**
3. Git이 없다면 https://git-scm.com/downloads 에서 설치 (기본 옵션 그대로 Next만 눌러도 됨)

그 창(PowerShell)에 아래를 순서대로 붙여넣고 Enter:

```powershell
git clone https://github.com/doookyung/yt-sheet-pdf.git
cd yt-sheet-pdf
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python sheet2pdf.py "https://www.youtube.com/watch?v=XXXXXXXX"
```

이후 사용법은 위와 같고, `./sheet2pdf` 대신 `.venv\Scripts\python sheet2pdf.py` 를 쓰면 됩니다.

---

## 동작 원리 (궁금한 사람만)

1. `yt-dlp`로 영상 스트림만 받음 (소리 없이, ffmpeg 불필요)
2. 선택한 영역을 0.5초 간격으로 잘라 작은 흑백 이미지로 변환
3. 마지막으로 저장한 페이지와 비교해 "눈에 띄게 달라진 픽셀 비율"이 기준을 넘으면 페이지가 넘어간 것으로 판단
4. 화면이 잠깐 멈추면(전환 애니메이션이 끝나면) 그 장면을 원본 해상도로 저장
5. 밝기 필터·중복 필터를 거쳐 Pillow로 PDF 조립
