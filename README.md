# yt-sheet-pdf

유튜브 영상(또는 로컬 영상 파일)에서 **악보/탭이 나오는 영역**을 지정하면,
악보가 넘어갈 때마다 자동으로 캡쳐해서 PNG + PDF로 만들어 줍니다.

- 재생 커서(하이라이트 바)가 움직이는 건 무시하고, **악보 줄이 실제로 바뀔 때만** 캡쳐
- 반복 구간(같은 악보가 다시 나올 때)은 자동으로 중복 제거
- 악보가 아닌 장면(인트로, 연주 화면 등)은 자동으로 제외
- ffmpeg 불필요 (yt-dlp로 비디오 스트림만 다운로드)

## 설치 (Mac / Linux, Python 3.10 이상 필요)

```bash
git clone https://github.com/<your-id>/yt-sheet-pdf.git
cd yt-sheet-pdf
./setup.sh
```

Windows는 `python -m venv .venv && .venv\Scripts\pip install -r requirements.txt` 후
`.venv\Scripts\python sheet2pdf.py ...` 로 실행하면 됩니다.

## 사용법

```bash
# 1) 가장 기본: URL만 주면 창이 뜨고, 악보 영역을 마우스로 드래그한 뒤 Enter
./sheet2pdf "https://www.youtube.com/watch?v=XXXX"

# 2) 영역을 숫자로 직접 지정 (x,y,w,h) - GUI 없이 실행
./sheet2pdf "https://youtu.be/XXXX" --region 0,0,1280,340

# 3) 특정 구간만, 로컬 파일로
./sheet2pdf lesson.mp4 --start 1:50 --end 4:30 --region full

# 4) 잘못 잡힌 PNG를 output/pages 에서 지운 뒤 PDF만 다시 만들기
./sheet2pdf --from-images output/pages --name my_song.pdf
```

> 영역 선택 창이 안 보이면 Dock의 Python 아이콘을 클릭하세요 (터미널 뒤에 열릴 수 있음).

결과는 `output/` 폴더에 저장됩니다.

```
output/
├── pages/page_001_01m52s.png   ← 캡쳐된 낱장 (파일명에 영상 시각)
├── pages/page_002_02m02s.png
└── <영상 제목>.pdf             ← A4 비율로 위에서부터 차곡차곡 배치
```

GUI로 영역을 고르면 터미널에 `--region 0,0,1280,340` 처럼 출력되므로
같은 채널 영상에는 그 값을 복사해서 재사용하면 됩니다.

## 옵션

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--region x,y,w,h` / `full` | (GUI) | 악보 영역. 원본 해상도 기준 픽셀 |
| `--pick-at 2:00` | 구간 중간 | GUI 영역 선택 화면에 띄울 시각 |
| `--start`, `--end` | 전체 | 분석 구간 (`90`, `1:30`, `1m30s` 모두 가능) |
| `--interval` | 0.5 | 프레임 검사 간격(초). 페이지가 아주 빨리 넘어가면 0.25 |
| `--threshold` | 0.06 | 페이지 전환으로 볼 변화 비율. 커서까지 잡히면 올리고, 전환을 놓치면 내림 |
| `--settle` | 2 | 전환 뒤 이만큼 연속으로 화면이 멈추면 캡쳐 (전환 애니메이션 도중 캡쳐 방지) |
| `--dedup` | 0.02 | 이전 페이지와 이 비율 미만으로 다르면 중복. `0`이면 끔 |
| `--min-bright` | 0.5 | 밝은 픽셀 비율이 이보다 낮으면 악보가 아니라고 판단. **다크 테마 악보면 `0`** |
| `--per-page` | 자동 | PDF 한 장에 넣을 캡쳐 수 (`1`이면 한 장에 하나) |
| `--max-height` | 1080 | 다운로드 최대 해상도 |
| `--keep-video` | | 다운로드한 영상 파일 삭제하지 않음 |
| `--debug` | | 프레임별 변화량을 출력 (threshold 튜닝용) |

## 동작 원리

1. `yt-dlp`로 비디오 스트림만 받음 (h264 mp4 우선)
2. 선택한 영역을 일정 간격으로 잘라 저해상도 그레이스케일로 변환
3. 마지막으로 저장한 페이지와 비교해 "눈에 띄게 달라진 픽셀 비율"이 `--threshold`를 넘으면 전환으로 판단
4. 화면이 `--settle`번 연속 안정되면 그 프레임을 원본 해상도로 저장
5. 밝기 필터 / 중복 필터를 거친 뒤 Pillow로 PDF 조립

## 팁

- 스크롤 방식(악보가 계속 흘러가는) 영상은 페이지가 겹치게 여러 장 잡힙니다. `--threshold`를 0.3 정도로 올리면 대략 한 화면 분량마다 잡힙니다.
- 캡쳐가 너무 많거나 적으면 `--debug`로 시간별 변화량을 보고 `--threshold`를 조절하세요.
