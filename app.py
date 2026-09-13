#!/usr/bin/env python3
"""
yt-sheet-pdf GUI - 더블클릭으로 실행하는 창 버전.

흐름:  링크 입력 → [영상 불러오기] → 미리보기에서 악보 영역 드래그
       → [PDF 만들기] → 썸네일에서 잘못 잡힌 장 체크 해제 → [PDF 다시 만들기]
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

import sheet2pdf as core

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
PREVIEW_W, PREVIEW_H = 880, 400
THUMB_W = 260


def open_path(p: Path):
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    elif os.name == "nt":
        os.startfile(str(p))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(p)])


# macOS 가상 키코드 (한글 입력 상태에서는 keysym 이 'ㅍ' 등으로 와서 keycode 로 판별)
_MAC_KEYCODES = {9: "paste", 8: "copy", 7: "cut", 0: "selectall"}
_KEYSYMS = {"v": "paste", "c": "copy", "x": "cut", "a": "selectall"}


def install_edit_shortcuts(w: tk.Widget):
    """⌘V/⌘C/⌘X/⌘A (Ctrl 포함) 를 입력기와 무관하게 동작시키고 우클릭 메뉴를 붙인다."""
    def do(action: str):
        if action == "selectall":
            w.select_range(0, "end")
            w.icursor("end")
        else:
            w.event_generate(f"<<{action.capitalize()}>>")

    def on_key(e):
        action = _KEYSYMS.get((e.keysym or "").lower()) or (
            _MAC_KEYCODES.get(e.keycode) if sys.platform == "darwin" else None)
        if action:
            do(action)
            return "break"

    w.bind("<Command-KeyPress>", on_key)
    w.bind("<Control-KeyPress>", on_key)

    menu = tk.Menu(w, tearoff=0)
    menu.add_command(label="붙여넣기", command=lambda: do("paste"))
    menu.add_command(label="복사", command=lambda: do("copy"))
    menu.add_command(label="잘라내기", command=lambda: do("cut"))
    menu.add_separator()
    menu.add_command(label="모두 선택", command=lambda: do("selectall"))
    menu.add_command(label="지우기", command=lambda: w.delete(0, "end"))

    def popup(e):
        w.focus_set()
        menu.tk_popup(e.x_root, e.y_root)
    w.bind("<Button-2>", popup)        # macOS 트랙패드 우클릭
    w.bind("<Button-3>", popup)
    w.bind("<Control-Button-1>", popup)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("YouTube 악보 → PDF")
        self.geometry("960x900")
        self.minsize(820, 720)

        self.video: Path | None = None
        self.video_title: str | None = None
        self.fps = 30.0
        self.duration = 0.0
        self.frame_w = self.frame_h = 0
        self.region: core.Region | None = None
        self.pages: list[core.Capture] = []
        self.page_vars: list[tk.BooleanVar] = []
        self.pdf_path: Path | None = None
        self.worker: threading.Thread | None = None
        self.stop_flag = False
        self.q: queue.Queue = queue.Queue()

        self._preview_img = None       # PhotoImage 참조 유지
        self._preview_scale = 1.0
        self._off = (0, 0)             # 캔버스 안에서 프레임이 그려지는 좌상단 오프셋
        self._drag_start = None
        self._rect_id = None
        self._thumb_refs: list = []

        self._last_autofill = ""
        self._build_ui()
        self.after(100, self._poll_queue)
        self.after(300, self._autofill_from_clipboard)
        self.bind("<FocusIn>", self._autofill_from_clipboard)

    # ─────────────────────────── UI 구성 ───────────────────────────

    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}

        # 1. 소스 입력
        f1 = ttk.LabelFrame(self, text="1. 유튜브 링크 또는 영상 파일")
        f1.pack(fill="x", **pad)
        self.src_var = tk.StringVar()
        self.src_entry = ttk.Entry(f1, textvariable=self.src_var)
        self.src_entry.pack(side="left", fill="x", expand=True, padx=(8, 4), pady=8)
        install_edit_shortcuts(self.src_entry)
        # 자동으로 채워진 링크 위에 붙여넣기하면 이어붙지 않고 교체
        self.src_entry.bind("<<Paste>>", self._replace_autofill_on_paste, add=True)
        ttk.Button(f1, text="📋 붙여넣기", command=self._paste_clipboard).pack(side="left", padx=4)
        ttk.Button(f1, text="파일 선택…", command=self._choose_file).pack(side="left", padx=4)
        self.load_btn = ttk.Button(f1, text="영상 불러오기", command=self._load_video)
        self.load_btn.pack(side="left", padx=(4, 8))

        # 2. 미리보기 + 영역 드래그
        f2 = ttk.LabelFrame(self, text="2. 악보 영역을 마우스로 드래그하세요")
        f2.pack(fill="x", **pad)
        self.canvas = tk.Canvas(f2, width=PREVIEW_W, height=PREVIEW_H, bg="#222", cursor="crosshair",
                                highlightthickness=0)
        self.canvas.pack(padx=8, pady=(8, 4))
        self.canvas.create_text(PREVIEW_W // 2, PREVIEW_H // 2, fill="#888", font=("", 14),
                                text="영상을 불러오면 여기에 장면이 표시됩니다", tags="hint")
        self.canvas.bind("<ButtonPress-1>", self._drag_begin)
        self.canvas.bind("<B1-Motion>", self._drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._drag_end)

        row = ttk.Frame(f2)
        row.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(row, text="장면 시각").pack(side="left")
        self.time_var = tk.DoubleVar(value=0)
        self.time_scale = ttk.Scale(row, from_=0, to=1, variable=self.time_var, command=self._on_scrub)
        self.time_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.time_lbl = ttk.Label(row, text="00m00s", width=8)
        self.time_lbl.pack(side="left")
        self.region_lbl = ttk.Label(row, text="영역: (없음)", width=28, anchor="e")
        self.region_lbl.pack(side="left", padx=(12, 0))
        ttk.Button(row, text="전체 화면", command=self._region_full).pack(side="left", padx=4)
        self.time_scale.bind("<ButtonRelease-1>", lambda e: self._show_frame(self.time_var.get()))

        # 3. 옵션
        f3 = ttk.LabelFrame(self, text="3. 옵션")
        f3.pack(fill="x", **pad)
        r = ttk.Frame(f3)
        r.pack(fill="x", padx=8, pady=6)
        ttk.Label(r, text="시작").pack(side="left")
        self.start_var = tk.StringVar(value="0:00")
        e_start = ttk.Entry(r, textvariable=self.start_var, width=7)
        e_start.pack(side="left", padx=(4, 12))
        install_edit_shortcuts(e_start)
        ttk.Label(r, text="끝").pack(side="left")
        self.end_var = tk.StringVar(value="")
        e_end = ttk.Entry(r, textvariable=self.end_var, width=7)
        e_end.pack(side="left", padx=(4, 12))
        install_edit_shortcuts(e_end)
        ttk.Label(r, text="감도").pack(side="left")
        self.thr_var = tk.DoubleVar(value=0.06)
        ttk.Scale(r, from_=0.01, to=0.3, variable=self.thr_var, length=140,
                  command=lambda v: self.thr_lbl.config(text=f"{float(v):.2f}")).pack(side="left", padx=4)
        self.thr_lbl = ttk.Label(r, text="0.06", width=5)
        self.thr_lbl.pack(side="left")
        ttk.Label(r, text="(커서까지 잡히면 ▶, 전환을 놓치면 ◀)", foreground="#777").pack(side="left", padx=(0, 12))
        self.dark_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="어두운 배경 악보", variable=self.dark_var).pack(side="left", padx=4)
        self.one_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r, text="PDF 한 장에 하나씩", variable=self.one_var).pack(side="left", padx=4)

        # 4. 실행 + 진행
        f4 = ttk.Frame(self)
        f4.pack(fill="x", **pad)
        self.run_btn = ttk.Button(f4, text="▶  PDF 만들기", command=self._run, state="disabled")
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(f4, text="중지", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)
        self.prog = ttk.Progressbar(f4, mode="determinate", maximum=1.0)
        self.prog.pack(side="left", fill="x", expand=True, padx=8)
        self.status_lbl = ttk.Label(f4, text="영상을 불러와 주세요", width=34, anchor="w")
        self.status_lbl.pack(side="left")

        # 로그 (맨 아래 고정)
        self.log_txt = tk.Text(self, height=4, font=("Menlo", 10), state="disabled")
        self.log_txt.pack(side="bottom", fill="x", padx=10, pady=(0, 8))

        # 5. 결과
        f5 = ttk.LabelFrame(self, text="4. 결과 — 잘못 잡힌 장은 체크를 해제하고 [PDF 다시 만들기]")
        f5.pack(fill="both", expand=True, **pad)
        top = ttk.Frame(f5)
        top.pack(fill="x", padx=8, pady=(6, 2))
        self.open_pdf_btn = ttk.Button(top, text="PDF 열기", command=lambda: self.pdf_path and open_path(self.pdf_path),
                                       state="disabled")
        self.open_pdf_btn.pack(side="left")
        ttk.Button(top, text="폴더 열기", command=lambda: open_path(OUT_DIR)).pack(side="left", padx=6)
        self.rebuild_btn = ttk.Button(top, text="PDF 다시 만들기", command=self._rebuild, state="disabled")
        self.rebuild_btn.pack(side="left", padx=6)
        self.result_lbl = ttk.Label(top, text="", foreground="#555")
        self.result_lbl.pack(side="left", padx=10)

        wrap = ttk.Frame(f5)
        wrap.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self.thumb_canvas = tk.Canvas(wrap, highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.thumb_canvas.yview)
        self.thumb_canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.thumb_canvas.pack(side="left", fill="both", expand=True)
        self.thumb_inner = ttk.Frame(self.thumb_canvas)
        self.thumb_canvas.create_window((0, 0), window=self.thumb_inner, anchor="nw")
        self.thumb_inner.bind("<Configure>",
                              lambda e: self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all")))
        self.thumb_canvas.bind_all("<MouseWheel>", self._on_wheel)

    # ─────────────────────────── 헬퍼 ───────────────────────────

    def log(self, msg: str):
        self.q.put(("log", msg))

    def _poll_queue(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log_txt.config(state="normal")
                    self.log_txt.insert("end", val + "\n")
                    self.log_txt.see("end")
                    self.log_txt.config(state="disabled")
                elif kind == "progress":
                    self.prog["value"] = val
                elif kind == "status":
                    self.status_lbl.config(text=val)
                elif kind == "call":
                    val()
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _set_status(self, s: str):
        self.q.put(("status", s))

    def _busy(self, on: bool):
        state = "disabled" if on else "normal"
        self.load_btn.config(state=state)
        self.run_btn.config(state="disabled" if on or self.region is None else "normal")
        self.stop_btn.config(state="normal" if on else "disabled")
        self.rebuild_btn.config(state="disabled" if on or not self.pages else "normal")

    def _on_wheel(self, e):
        self.thumb_canvas.yview_scroll(int(-e.delta / 30) if abs(e.delta) > 10 else -e.delta, "units")

    # ─────────────────────────── 클립보드 ───────────────────────────

    def _clipboard_text(self) -> str:
        try:
            return self.clipboard_get().strip()
        except tk.TclError:
            return ""

    def _replace_autofill_on_paste(self, _e=None):
        if self.src_var.get().strip() and self.src_var.get().strip() == self._last_autofill:
            self.src_entry.delete(0, "end")

    def _paste_clipboard(self):
        txt = self._clipboard_text()
        if not txt:
            messagebox.showinfo("안내", "클립보드가 비어 있습니다. 유튜브 링크를 먼저 복사(⌘C)하세요.")
            return
        self.src_var.set(txt.splitlines()[0])
        self._last_autofill = self.src_var.get()

    def _autofill_from_clipboard(self, _e=None):
        """클립보드에 유튜브 링크가 있고 입력칸이 비어 있으면(또는 직전 자동입력 그대로면) 자동으로 채운다.
        앱 시작 시, 그리고 다른 앱에서 돌아와 창이 활성화될 때만 (입력칸 클릭에는 반응하지 않음)."""
        if _e is not None and _e.widget is not self:
            return
        txt = self._clipboard_text().splitlines()[0] if self._clipboard_text() else ""
        if not txt or not core.is_url(txt) or "yout" not in txt.lower():
            return
        cur = self.src_var.get().strip()
        if cur == "" or cur == self._last_autofill:
            if cur != txt:
                self.src_var.set(txt)
                self._last_autofill = txt
                self._set_status("클립보드의 링크를 자동으로 넣었어요 → [영상 불러오기]")

    # ─────────────────────────── 1. 영상 불러오기 ───────────────────────────

    def _choose_file(self):
        p = filedialog.askopenfilename(filetypes=[("영상", "*.mp4 *.mkv *.webm *.mov *.avi"), ("모두", "*.*")])
        if p:
            self.src_var.set(p)

    def _load_video(self):
        src = self.src_var.get().strip()
        if not src:
            messagebox.showinfo("안내", "유튜브 링크를 붙여넣거나 영상 파일을 선택하세요.")
            return
        self._busy(True)
        self.prog["value"] = 0
        self.region = None
        self.region_lbl.config(text="영역: (없음)")

        def work():
            try:
                if core.is_url(src):
                    self._set_status("다운로드 중…")
                    video, title = core.download_video(src, OUT_DIR, 1080, log=self.log,
                                                       progress=lambda f: self.q.put(("progress", f)))
                else:
                    video, title = Path(src), Path(src).stem
                    if not video.exists():
                        raise FileNotFoundError(src)
                fps, dur, w, h = core.probe_video(video)
                self.video, self.video_title = video, title
                self.fps, self.duration, self.frame_w, self.frame_h = fps, dur, w, h
                self.log(f"[video] {w}x{h}, {fps:.2f}fps, {core.fmt_time(dur)}")
                self.q.put(("call", self._after_load))
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                self.log(f"[error] {msg}")
                self.q.put(("call", lambda: messagebox.showerror("오류", msg)))
                self.q.put(("call", lambda: self._busy(False)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _after_load(self):
        self.time_scale.config(to=max(1.0, self.duration))
        mid = self.duration / 2
        self.time_var.set(mid)
        self._on_scrub(mid)
        self._show_frame(mid)
        self._busy(False)
        self._set_status("악보 영역을 드래그하세요")
        self.prog["value"] = 0

    # ─────────────────────────── 2. 미리보기 / 영역 ───────────────────────────

    def _on_scrub(self, v):
        self.time_lbl.config(text=core.fmt_time(float(v)))

    def _show_frame(self, t: float):
        if not self.video:
            return
        frame = core.read_frame(self.video, min(t, max(0.0, self.duration - 0.1)))
        if frame is None:
            return
        self.canvas.delete("hint")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        scale = min(PREVIEW_W / self.frame_w, PREVIEW_H / self.frame_h)
        self._preview_scale = scale
        im = Image.fromarray(rgb).resize((int(self.frame_w * scale), int(self.frame_h * scale)), Image.BILINEAR)
        self._preview_img = ImageTk.PhotoImage(im)
        self._off = ((PREVIEW_W - im.width) // 2, (PREVIEW_H - im.height) // 2)
        self.canvas.delete("frame")
        self.canvas.create_image(*self._off, anchor="nw", image=self._preview_img, tags="frame")
        self.canvas.tag_lower("frame")
        self._draw_region()

    def _draw_region(self):
        self.canvas.delete("region")
        if self.region is None:
            return
        s = self._preview_scale
        ox, oy = self._off
        r = self.region
        self.canvas.create_rectangle(ox + r.x * s, oy + r.y * s, ox + (r.x + r.w) * s, oy + (r.y + r.h) * s,
                                     outline="#ff3b30", width=3, tags="region")
        self.region_lbl.config(text=f"영역: {r.x},{r.y},{r.w},{r.h}")

    def _drag_begin(self, e):
        if not self.video:
            return
        self._drag_start = (e.x, e.y)
        self.canvas.delete("region")
        self._rect_id = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff3b30", width=3, tags="region")

    def _drag_move(self, e):
        if self._drag_start and self._rect_id:
            x0, y0 = self._drag_start
            self.canvas.coords(self._rect_id, x0, y0, e.x, e.y)

    def _drag_end(self, e):
        if not self._drag_start:
            return
        x0, y0 = self._drag_start
        self._drag_start = None
        s = self._preview_scale
        ox, oy = self._off
        x1, x2 = sorted((x0 - ox, e.x - ox))
        y1, y2 = sorted((y0 - oy, e.y - oy))
        if x2 - x1 < 5 or y2 - y1 < 5:
            self.canvas.delete("region")
            return
        rx, ry = int(x1 / s), int(y1 / s)
        rw, rh = int((x2 - x1) / s), int((y2 - y1) / s)
        rx, ry = max(0, rx), max(0, ry)
        rw, rh = min(rw, self.frame_w - rx), min(rh, self.frame_h - ry)
        self.region = core.Region(rx, ry, rw, rh)
        self._draw_region()
        self.run_btn.config(state="normal")
        self._set_status("준비 완료 — [PDF 만들기]를 누르세요")

    def _region_full(self):
        if not self.video:
            return
        self.region = core.Region(0, 0, self.frame_w, self.frame_h)
        self._draw_region()
        self.run_btn.config(state="normal")
        self._set_status("준비 완료 — [PDF 만들기]를 누르세요")

    # ─────────────────────────── 3. 실행 ───────────────────────────

    def _run(self):
        if not self.video or not self.region:
            return
        try:
            start = core.parse_time(self.start_var.get() or "0") or 0.0
            end = core.parse_time(self.end_var.get()) if self.end_var.get().strip() else None
        except Exception:
            messagebox.showerror("오류", "시작/끝 시각 형식이 잘못됐습니다. 예: 1:30")
            return
        self.stop_flag = False
        self._busy(True)
        self.prog["value"] = 0
        self._clear_thumbs()
        self.pages = []
        self.pdf_path = None
        self.open_pdf_btn.config(state="disabled")
        region, thr = self.region, float(self.thr_var.get())
        min_bright = 0.0 if self.dark_var.get() else 0.5
        one_per_page = self.one_var.get()

        def work():
            try:
                self._set_status("악보 페이지 찾는 중…")
                pages = core.extract_pages(
                    self.video, region, start, end, 0.5, thr, 2, 0.02, min_bright,
                    log=self.log, progress=lambda f: self.q.put(("progress", f)),
                    should_stop=lambda: self.stop_flag,
                )
                self.pages = pages
                if pages:
                    core.save_pages(pages, OUT_DIR / "pages")
                    imgs = [Image.fromarray(cv2.cvtColor(p.image, cv2.COLOR_BGR2RGB)) for p in pages]
                    self._build_pdf(imgs, one_per_page)
                self.q.put(("call", self._after_run))
            except Exception as e:  # noqa: BLE001
                msg = f"{type(e).__name__}: {e}"
                self.log(f"[error] {msg}")
                self.q.put(("call", lambda: messagebox.showerror("오류", msg)))
                self.q.put(("call", lambda: self._busy(False)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _stop(self):
        self.stop_flag = True
        self._set_status("중지 중…")

    def _selected_images(self) -> list[Image.Image]:
        """메인 스레드에서만 호출 (tk 변수 읽음)."""
        keep = [v.get() for v in self.page_vars] if self.page_vars else [True] * len(self.pages)
        return [Image.fromarray(cv2.cvtColor(p.image, cv2.COLOR_BGR2RGB))
                for p, k in zip(self.pages, keep) if k]

    def _build_pdf(self, imgs: list[Image.Image], one_per_page: bool):
        """작업 스레드에서 호출 가능 (tk 변수 안 읽음)."""
        if not imgs:
            self.log("[pdf] 선택된 장이 없습니다.")
            return
        self.pdf_path = OUT_DIR / core.safe_pdf_name(self.video_title)
        core.make_pdf(imgs, self.pdf_path, 1 if one_per_page else None, log=self.log)

    def _after_run(self):
        self._busy(False)
        self.prog["value"] = 1.0
        n = len(self.pages)
        if n == 0:
            self._set_status("감지된 페이지가 없습니다")
            messagebox.showinfo("결과", "악보 페이지를 찾지 못했습니다.\n감도를 낮추거나(◀) 영역을 다시 지정해 보세요.\n"
                                        "어두운 배경 악보라면 옵션을 켜세요.")
            return
        self._set_status(f"완료! {n}장 → PDF 저장됨")
        self.result_lbl.config(text=f"{n}장 캡쳐  ·  {self.pdf_path.name if self.pdf_path else ''}")
        self.open_pdf_btn.config(state="normal")
        self.rebuild_btn.config(state="normal")
        self._show_thumbs()

    # ─────────────────────────── 4. 썸네일 / 재생성 ───────────────────────────

    def _clear_thumbs(self):
        for w in self.thumb_inner.winfo_children():
            w.destroy()
        self._thumb_refs.clear()
        self.page_vars.clear()

    def _show_thumbs(self):
        self._clear_thumbs()
        cols = max(1, (self.thumb_canvas.winfo_width() or 900) // (THUMB_W + 16))
        for i, p in enumerate(self.pages):
            rgb = cv2.cvtColor(p.image, cv2.COLOR_BGR2RGB)
            im = Image.fromarray(rgb)
            im.thumbnail((THUMB_W, THUMB_W))
            ph = ImageTk.PhotoImage(im)
            self._thumb_refs.append(ph)
            var = tk.BooleanVar(value=True)
            self.page_vars.append(var)
            cell = ttk.Frame(self.thumb_inner, padding=4)
            cell.grid(row=i // cols, column=i % cols, sticky="n")
            lbl = tk.Label(cell, image=ph, bd=1, relief="solid")
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, v=var: v.set(not v.get()))
            ttk.Checkbutton(cell, text=f"{i + 1}. {core.fmt_time(p.time)}", variable=var).pack()
        self.thumb_inner.update_idletasks()
        self.thumb_canvas.configure(scrollregion=self.thumb_canvas.bbox("all"))
        self.thumb_canvas.yview_moveto(0)

    def _rebuild(self):
        if not self.pages:
            return
        self._busy(True)
        imgs = self._selected_images()
        one_per_page = self.one_var.get()
        n = len(imgs)

        def work():
            try:
                self._set_status("PDF 다시 만드는 중…")
                self._build_pdf(imgs, one_per_page)
                self.q.put(("call", lambda: self._set_status(f"완료! {n}장 → PDF 저장됨")))
                self.q.put(("call", lambda: self.result_lbl.config(
                    text=f"{n}장 선택  ·  {self.pdf_path.name if self.pdf_path else ''}")))
            except Exception as e:  # noqa: BLE001
                self.log(f"[error] {e}")
            finally:
                self.q.put(("call", lambda: self._busy(False)))

        threading.Thread(target=work, daemon=True).start()


def main():
    OUT_DIR.mkdir(exist_ok=True)
    app = App()
    # macOS: 앱 창을 앞으로
    if sys.platform == "darwin":
        try:
            app.lift()
            app.attributes("-topmost", True)
            app.after(300, lambda: app.attributes("-topmost", False))
        except tk.TclError:
            pass
    app.mainloop()


if __name__ == "__main__":
    main()
