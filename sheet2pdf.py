#!/usr/bin/env python3
"""
sheet2pdf - 유튜브 영상에서 악보(탭) 영역이 바뀔 때마다 캡쳐해서 PDF로 만드는 도구.

사용 예:
    python sheet2pdf.py "https://youtu.be/XXXX"                # GUI로 영역 드래그 선택
    python sheet2pdf.py "https://youtu.be/XXXX" --region 0,600,1920,480
    python sheet2pdf.py local_video.mp4 --start 0:15 --end 3:40
    python sheet2pdf.py --from-images output/pages             # PNG 정리 후 PDF만 다시 생성
"""

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


# ─────────────────────────── 유틸 ────────────────────────────

def parse_time(s: str | None) -> float | None:
    """'90', '1:30', '1:02:03', '1m30s' → 초."""
    if s is None:
        return None
    s = s.strip()
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s)
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?", s)
    if m and any(m.groups()):
        h, mi, se = m.groups()
        return int(h or 0) * 3600 + int(mi or 0) * 60 + float(se or 0)
    parts = [float(p) for p in s.split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def fmt_time(t: float) -> str:
    t = int(t)
    return f"{t // 60:02d}m{t % 60:02d}s"


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "www.", "youtu"))


# ─────────────────────────── 다운로드 ────────────────────────────

def download_video(url: str, out_dir: Path, max_height: int,
                   log=print, progress=None) -> tuple[Path, str | None]:
    """비디오 스트림만(오디오 없이) 받아서 ffmpeg 없이도 동작하게 한다.
    progress(fraction 0~1) 콜백은 GUI 진행 표시용."""
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    # 이전에 받아둔 영상이 남아 있으면 yt-dlp 가 "이미 다운로드됨"으로 건너뛰므로 먼저 정리
    for old in out_dir.glob("video*.*"):
        if old.suffix.lower() in (".mp4", ".webm", ".mkv", ".part", ".ytdl"):
            old.unlink(missing_ok=True)
    have_ffmpeg = shutil.which("ffmpeg") is not None
    # h264 mp4 를 우선 (OpenCV 호환성). ffmpeg 이 있으면 합치기 가능한 포맷도 허용.
    fmt = (
        f"bv*[ext=mp4][vcodec^=avc1][height<={max_height}]"
        f"/bv*[ext=mp4][height<={max_height}]"
        f"/b[ext=mp4][height<={max_height}]"
        f"/bv*[height<={max_height}]/b"
    )
    opts = {
        "format": fmt,
        "outtmpl": str(out_dir / "video_%(id)s.%(ext)s"),
        "noplaylist": True,
        "overwrites": True,
        "quiet": progress is not None,
        "noprogress": progress is not None,
        "no_warnings": True,
    }
    if progress is not None:
        def _hook(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total:
                    progress(d.get("downloaded_bytes", 0) / total)
            elif d.get("status") == "finished":
                progress(1.0)
        opts["progress_hooks"] = [_hook]
    if not have_ffmpeg:
        # ffmpeg 없으면 병합/재인코딩이 필요한 포맷은 피한다 (비디오 단독 스트림은 병합 불필요)
        opts["prefer_ffmpeg"] = False

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():
        cands = sorted(out_dir.glob("video.*"))
        if not cands:
            sys.exit("다운로드된 파일을 찾을 수 없습니다.")
        path = cands[0]
    log(f"[download] {path.name} ({info.get('title', '')})")
    return path, info.get("title")


# ─────────────────────────── 영역 선택 ────────────────────────────

@dataclass
class Region:
    x: int
    y: int
    w: int
    h: int

    def crop(self, frame: np.ndarray) -> np.ndarray:
        return frame[self.y : self.y + self.h, self.x : self.x + self.w]


def parse_region(s: str, frame_w: int, frame_h: int) -> Region:
    if s == "full":
        return Region(0, 0, frame_w, frame_h)
    try:
        x, y, w, h = (int(v) for v in s.split(","))
    except ValueError:
        sys.exit("--region 은 'x,y,w,h' 또는 'full' 형식이어야 합니다.")
    x, y = max(0, x), max(0, y)
    w, h = min(w, frame_w - x), min(h, frame_h - y)
    if w <= 0 or h <= 0:
        sys.exit("--region 이 영상 범위를 벗어났습니다.")
    return Region(x, y, w, h)


def select_region_gui(frame: np.ndarray) -> Region:
    """OpenCV 창에서 드래그로 영역 선택. Enter/Space 확정, c 취소."""
    h, w = frame.shape[:2]
    scale = min(1.0, 1400 / w, 800 / h)  # 화면에 들어오게 축소
    shown = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame.copy()
    win = "Select sheet-music area (ENTER=ok, c=cancel)"
    cv2.putText(shown, "Drag the sheet-music area, then press ENTER", (10, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    print("\n[region] 영역 선택 창을 엽니다. 창이 안 보이면 Dock의 Python 아이콘을 클릭하세요.")
    print("         악보 부분을 마우스로 드래그한 뒤 Enter (취소: c)\n")
    cv2.namedWindow(win, cv2.WINDOW_AUTOSIZE)
    cv2.imshow(win, shown)
    cv2.waitKey(1)
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_TOPMOST, 1)  # 맨 앞으로
    except cv2.error:
        pass
    x, y, rw, rh = cv2.selectROI(win, shown, showCrosshair=False, fromCenter=False)
    cv2.destroyAllWindows()
    if rw == 0 or rh == 0:
        sys.exit("영역이 선택되지 않았습니다. --region x,y,w,h 로 직접 지정할 수도 있습니다.")
    inv = 1 / scale
    reg = Region(int(x * inv), int(y * inv), int(rw * inv), int(rh * inv))
    reg.w = min(reg.w, w - reg.x)
    reg.h = min(reg.h, h - reg.y)
    print(f"[region] --region {reg.x},{reg.y},{reg.w},{reg.h}  (다음에 GUI 없이 재사용 가능)")
    return reg


# ─────────────────────────── 변화 감지 ────────────────────────────

def signature(crop: np.ndarray, width: int = 320) -> np.ndarray:
    """비교용 저해상도 그레이스케일 (약간 블러로 압축 노이즈 제거)."""
    h, w = crop.shape[:2]
    small = cv2.resize(crop, (width, max(1, int(h * width / w))), interpolation=cv2.INTER_AREA)
    g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    return cv2.GaussianBlur(g, (3, 3), 0)


def changed_ratio(a: np.ndarray, b: np.ndarray, pixel_thresh: int = 40) -> float:
    """두 시그니처 사이에 '눈에 띄게' 달라진 픽셀 비율 (0~1)."""
    d = cv2.absdiff(a, b)
    return float((d > pixel_thresh).mean())


def bright_ratio(sig: np.ndarray) -> float:
    """밝은(흰 배경) 픽셀 비율. 악보는 보통 0.7 이상, 연주 장면/검은 화면은 0.2 이하."""
    return float((sig > 200).mean())


@dataclass
class Capture:
    index: int
    time: float
    image: np.ndarray  # 원본 해상도 크롭 (BGR)
    sig: np.ndarray


def extract_pages(
    video_path: Path,
    region: Region,
    start: float,
    end: float | None,
    interval: float,
    threshold: float,
    settle: int,
    dedup: float | None,
    min_bright: float = 0.0,
    debug_dir: Path | None = None,
    log=print,
    progress=None,
    should_stop=None,
) -> list[Capture]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        sys.exit(f"영상을 열 수 없습니다: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = n_frames / fps
    end = min(end, duration) if end else duration
    step = max(1, int(round(interval * fps)))
    log(f"[scan] {fmt_time(start)} → {fmt_time(end)}, {interval}s 간격, "
        f"threshold={threshold}, settle={settle}")

    pages: list[Capture] = []
    ref_sig: np.ndarray | None = None      # 마지막으로 저장한 페이지
    pending: tuple[np.ndarray, np.ndarray, float] | None = None  # (sig, crop, t)
    stable_count = 0
    skipped_dark = 0
    frame_idx = int(start * fps)
    last_report = -1

    while True:
        t = frame_idx / fps
        if t > end or (should_stop is not None and should_stop()):
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            break
        crop = region.crop(frame)
        sig = signature(crop)

        if ref_sig is None:
            # 첫 프레임은 무조건 첫 페이지
            pending, stable_count = (sig, crop.copy(), t), settle
        else:
            diff_ref = changed_ratio(sig, ref_sig)
            if debug_dir is not None:
                log(f"  t={t:7.2f}s diff={diff_ref:.4f}")
            if diff_ref > threshold:
                # 이전 페이지와 다름 → 화면이 멈출 때까지(전환 애니메이션 끝) 기다린다
                if pending is not None and changed_ratio(sig, pending[0]) <= threshold:
                    stable_count += 1
                else:
                    pending, stable_count = (sig, crop.copy(), t), 1
            else:
                pending, stable_count = None, 0

        if pending is not None and stable_count >= settle:
            psig, pcrop, pt = pending
            dup = False
            if min_bright > 0 and bright_ratio(psig) < min_bright:
                dup = True
                skipped_dark += 1
                if debug_dir is not None:
                    log(f"  [skip] {fmt_time(pt)} - 악보처럼 보이지 않음 (bright={bright_ratio(psig):.2f})")
            if not dup and dedup is not None:
                for p in pages:
                    if changed_ratio(psig, p.sig) < dedup:
                        dup = True
                        log(f"  [skip] {fmt_time(pt)} - page {p.index} 와 동일 (반복 구간)")
                        break
            if not dup:
                pages.append(Capture(len(pages) + 1, pt, pcrop, psig))
                log(f"  [page {len(pages):3d}] {fmt_time(pt)}")
            ref_sig = psig
            pending, stable_count = None, 0

        frame_idx += step
        frac = (t - start) / max(1e-6, end - start)
        if progress is not None:
            progress(min(1.0, frac))
        pct = int(frac * 100)
        if pct // 10 != last_report // 10 and debug_dir is None and progress is None:
            last_report = pct
            print(f"  ... {pct}%", end="\r", flush=True)

    cap.release()
    log(f"[scan] 총 {len(pages)} 페이지 감지"
        + (f", 악보가 아닌 장면 {skipped_dark}개 제외 (--min-bright 0 으로 끌 수 있음)" if skipped_dark else ""))
    return pages


# ─────────────────────────── PDF 생성 ────────────────────────────

def make_pdf(images: list[Image.Image], out_path: Path, per_page: int | None,
             page_width: int = 1654, page_ratio: float = 1.4142, margin: int = 40, gap: int = 24,
             log=print):
    """
    이미지(가로 스트립)를 A4 비율 페이지에 위에서부터 차곡차곡 쌓는다.
    per_page=None 이면 들어가는 만큼 자동, per_page=1 이면 한 장에 하나.
    """
    if not images:
        sys.exit("PDF 로 만들 이미지가 없습니다.")
    page_h = int(page_width * page_ratio)
    inner_w = page_width - 2 * margin

    pages: list[Image.Image] = []
    cur = None
    y = margin
    count = 0

    def new_page():
        return Image.new("RGB", (page_width, page_h), "white")

    for im in images:
        im = im.convert("RGB")
        scale = inner_w / im.width
        im = im.resize((inner_w, max(1, int(im.height * scale))), Image.LANCZOS)
        if im.height > page_h - 2 * margin:  # 너무 길면 페이지에 맞춤
            s = (page_h - 2 * margin) / im.height
            im = im.resize((max(1, int(im.width * s)), page_h - 2 * margin), Image.LANCZOS)

        need_new = cur is None or y + im.height > page_h - margin or (per_page and count >= per_page)
        if need_new:
            if cur is not None:
                pages.append(cur)
            cur, y, count = new_page(), margin, 0
        cur.paste(im, ((page_width - im.width) // 2, y))
        y += im.height + gap
        count += 1
    if cur is not None:
        pages.append(cur)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(out_path, "PDF", resolution=200, save_all=True, append_images=pages[1:])
    log(f"[pdf] {out_path}  ({len(pages)} 페이지, 이미지 {len(images)}장)")


def load_images_from_dir(d: Path) -> list[Image.Image]:
    files = sorted(p for p in d.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    if not files:
        sys.exit(f"{d} 에 이미지가 없습니다.")
    return [Image.open(f) for f in files]


def probe_video(video: Path) -> tuple[float, float, int, int]:
    """(fps, duration_sec, width, height)"""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        sys.exit(f"영상을 열 수 없습니다: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dur = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / fps
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return fps, dur, w, h


def read_frame(video: Path, t: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
    ok, frame = cap.read()
    cap.release()
    return frame if ok else None


def safe_pdf_name(title: str | None, override: str | None = None) -> str:
    safe = re.sub(r'[\\/:*?"<>|]+', "_", title).strip() if title else "sheet"
    name = override or f"{safe}.pdf"
    return name if name.lower().endswith(".pdf") else name + ".pdf"


def save_pages(pages: list[Capture], pages_dir: Path):
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True)
    for p in pages:
        cv2.imwrite(str(pages_dir / f"page_{p.index:03d}_{fmt_time(p.time)}.png"), p.image)


# ─────────────────────────── main ────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="유튜브 영상의 악보 부분을 페이지가 넘어갈 때마다 캡쳐해 PDF로 만듭니다.")
    ap.add_argument("source", nargs="?", help="유튜브 URL 또는 로컬 영상 파일")
    ap.add_argument("-o", "--output", default="output", help="출력 폴더 (기본: output)")
    ap.add_argument("--name", help="PDF 파일 이름 (기본: 영상 제목 또는 sheet.pdf)")
    ap.add_argument("--region", help="악보 영역 'x,y,w,h' 또는 'full'. 생략하면 GUI로 드래그 선택")
    ap.add_argument("--pick-at", default=None, help="영역 선택 화면에 띄울 시각 (기본: 구간 중간)")
    ap.add_argument("--start", default="0", help="분석 시작 시각 (예: 15, 1:30)")
    ap.add_argument("--end", default=None, help="분석 종료 시각")
    ap.add_argument("--interval", type=float, default=0.5, help="프레임 검사 간격(초). 기본 0.5")
    ap.add_argument("--threshold", type=float, default=0.06,
                    help="페이지 전환으로 볼 변화 비율(0~1). 커서 이동은 무시되고 페이지 넘김만 잡히게 조절. 기본 0.06")
    ap.add_argument("--settle", type=int, default=2, help="전환 후 이만큼 연속 안정되면 캡쳐. 기본 2")
    ap.add_argument("--dedup", type=float, default=0.02,
                    help="이전 페이지와 이 비율 미만으로 다르면 중복으로 건너뜀. 0이면 끔. 기본 0.02")
    ap.add_argument("--min-bright", type=float, default=0.5,
                    help="영역의 밝은 픽셀 비율이 이 값 미만이면 악보가 아니라고 보고 제외. 다크 테마 악보면 0. 기본 0.5")
    ap.add_argument("--per-page", type=int, default=None, help="PDF 한 장당 캡쳐 수 (기본: 자동으로 채움)")
    ap.add_argument("--max-height", type=int, default=1080, help="다운로드 최대 해상도. 기본 1080")
    ap.add_argument("--keep-video", action="store_true", help="다운로드한 영상 파일 유지")
    ap.add_argument("--from-images", metavar="DIR", help="이미 캡쳐된 PNG 폴더로 PDF만 다시 생성")
    ap.add_argument("--debug", action="store_true", help="프레임별 변화량 출력")
    args = ap.parse_args()

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── PDF 재생성 모드
    if args.from_images:
        imgs = load_images_from_dir(Path(args.from_images))
        make_pdf(imgs, out_dir / (args.name or "sheet.pdf"), args.per_page)
        return

    if not args.source:
        ap.error("유튜브 URL 또는 영상 파일을 지정하세요 (또는 --from-images).")

    # ── 영상 준비
    title = None
    if is_url(args.source):
        video, title = download_video(args.source, out_dir, args.max_height)
        downloaded = True
    else:
        video = Path(args.source)
        if not video.exists():
            sys.exit(f"파일이 없습니다: {video}")
        downloaded = False

    start = parse_time(args.start) or 0.0
    end = parse_time(args.end)

    # ── 영역 선택
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    dur = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) / fps
    pick_t = parse_time(args.pick_at)
    if pick_t is None:
        pick_t = (start + (min(end, dur) if end else dur)) / 2
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(pick_t * fps))
    ok, sample = cap.read()
    cap.release()
    if not ok:
        sys.exit("영상에서 프레임을 읽지 못했습니다.")
    fh, fw = sample.shape[:2]
    print(f"[video] {fw}x{fh}, {fps:.2f}fps, {fmt_time(dur)}")

    region = parse_region(args.region, fw, fh) if args.region else select_region_gui(sample)

    # ── 페이지 추출
    pages = extract_pages(
        video, region, start, end, args.interval, args.threshold, args.settle,
        args.dedup if args.dedup > 0 else None, args.min_bright, out_dir if args.debug else None,
    )
    if not pages:
        sys.exit("감지된 페이지가 없습니다. --threshold 를 낮추거나 --region 을 확인하세요.")

    pages_dir = out_dir / "pages"
    save_pages(pages, pages_dir)
    print(f"[pages] PNG 저장: {pages_dir}  (잘못 잡힌 장은 지우고 --from-images 로 PDF 재생성 가능)")

    # ── PDF
    pdf_name = safe_pdf_name(title, args.name)
    imgs = [Image.fromarray(cv2.cvtColor(p.image, cv2.COLOR_BGR2RGB)) for p in pages]
    make_pdf(imgs, out_dir / pdf_name, args.per_page)

    if downloaded and not args.keep_video:
        video.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
