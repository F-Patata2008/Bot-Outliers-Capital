import argparse
import os
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageGrab, ImageTk

try:
    import torch
    import torch.nn.functional as F
except ImportError as exc:
    torch = None
    F = None
    TORCH_IMPORT_ERROR = exc
else:
    TORCH_IMPORT_ERROR = None


APP_TITLE = "Asistente visual de compra"
DEFAULT_IMAGE = "Screenshot 2026-07-23 at 16-09-18 CIPC Challenge · Outliers Capital.png"


@dataclass
class AnalysisResult:
    signal: str
    confidence: float
    score: float
    green_pressure: float
    red_pressure: float
    momentum: float
    blue_coverage: float
    green_coverage: float
    red_coverage: float
    reason: str


def ensure_torch_available():
    if torch is None:
        raise RuntimeError(
            "PyTorch no esta instalado. Instala dependencias con: "
            "python3 -m pip install -r requirements.txt"
        ) from TORCH_IMPORT_ERROR


def image_to_tensor(image):
    ensure_torch_available()
    rgb = image.convert("RGB")
    data = torch.frombuffer(bytearray(rgb.tobytes()), dtype=torch.uint8)
    tensor = data.view(rgb.height, rgb.width, 3).float() / 255.0
    return tensor


def resize_for_analysis(tensor, max_side=900):
    height, width, _ = tensor.shape
    scale = min(1.0, max_side / float(max(height, width)))
    if scale == 1.0:
        return tensor

    resized = F.interpolate(
        tensor.permute(2, 0, 1).unsqueeze(0),
        size=(max(1, int(height * scale)), max(1, int(width * scale))),
        mode="bilinear",
        align_corners=False,
    )
    return resized.squeeze(0).permute(1, 2, 0)


def analyze_trading_image(image, threshold=0.18):
    """
    Heuristic visual analysis with PyTorch tensors.

    This is not a trading model. It measures visible chart/order-book cues:
    green-vs-red pressure and blue chart-line momentum.
    """
    tensor = resize_for_analysis(image_to_tensor(image))
    red = tensor[:, :, 0]
    green = tensor[:, :, 1]
    blue = tensor[:, :, 2]

    green_mask = (green > 0.36) & (green > red * 1.22) & (green > blue * 1.05)
    red_mask = (red > 0.36) & (red > green * 1.22) & (red > blue * 1.05)
    blue_mask = (blue > 0.48) & (blue > red * 1.35) & (blue > green * 1.04)

    pixel_count = tensor.shape[0] * tensor.shape[1]
    green_coverage = green_mask.float().mean().item()
    red_coverage = red_mask.float().mean().item()
    blue_coverage = blue_mask.float().mean().item()

    pressure_total = green_coverage + red_coverage + 1e-6
    green_pressure = green_coverage / pressure_total
    red_pressure = red_coverage / pressure_total

    momentum = estimate_blue_line_momentum(blue_mask)
    pressure_score = green_pressure - red_pressure
    score = 0.58 * pressure_score + 0.42 * momentum

    confidence = min(1.0, abs(score) / max(threshold, 1e-6))
    if score >= threshold:
        signal = "POSIBLE COMPRA"
        reason = "predominan zonas verdes y la linea azul muestra fuerza suficiente"
    elif score <= -threshold:
        signal = "NO COMPRAR"
        reason = "predominan zonas rojas o la linea azul pierde fuerza"
    else:
        signal = "ESPERAR"
        reason = "la imagen no tiene ventaja visual clara"

    if pixel_count == 0:
        confidence = 0.0

    return AnalysisResult(
        signal=signal,
        confidence=confidence,
        score=score,
        green_pressure=green_pressure,
        red_pressure=red_pressure,
        momentum=momentum,
        blue_coverage=blue_coverage,
        green_coverage=green_coverage,
        red_coverage=red_coverage,
        reason=reason,
    )


def estimate_blue_line_momentum(blue_mask):
    if blue_mask.numel() == 0 or blue_mask.float().mean().item() < 0.0001:
        return 0.0

    height, width = blue_mask.shape
    cols = blue_mask.float().sum(dim=0) > 0
    if cols.float().sum().item() < 8:
        return 0.0

    x_indices = torch.arange(width, device=blue_mask.device)
    active_x = x_indices[cols]
    left_limit = torch.quantile(active_x.float(), 0.20)
    right_limit = torch.quantile(active_x.float(), 0.80)

    y_indices = torch.arange(height, device=blue_mask.device).view(height, 1).float()
    col_weights = blue_mask.float().sum(dim=0).clamp_min(1e-6)
    y_center_by_col = (blue_mask.float() * y_indices).sum(dim=0) / col_weights

    left_cols = cols & (x_indices.float() <= left_limit)
    right_cols = cols & (x_indices.float() >= right_limit)
    if left_cols.float().sum().item() == 0 or right_cols.float().sum().item() == 0:
        return 0.0

    left_y = y_center_by_col[left_cols].mean()
    right_y = y_center_by_col[right_cols].mean()

    # In screen coordinates, a smaller y means the line is higher.
    raw = (left_y - right_y) / max(float(height), 1.0)
    return float(torch.clamp(raw * 3.0, min=-1.0, max=1.0).item())


class TradingAssistantApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1180x760")
        self.minsize(980, 640)

        self.current_image = None
        self.preview_image = None
        self.watch_job = None
        self.watch_running = False
        self.analysis_thread = None

        self.x_var = tk.StringVar(value="0")
        self.y_var = tk.StringVar(value="0")
        self.w_var = tk.StringVar(value="1920")
        self.h_var = tk.StringVar(value="1100")
        self.interval_var = tk.StringVar(value="2.0")
        self.threshold_var = tk.StringVar(value="0.18")
        self.status_var = tk.StringVar(value="Carga una imagen o captura pantalla para analizar.")
        self.signal_var = tk.StringVar(value="SIN ANALISIS")
        self.detail_var = tk.StringVar(value="")

        self._build_ui()
        self._load_default_image_if_present()

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(self, padding=(12, 10))
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.columnconfigure(9, weight=1)

        ttk.Button(toolbar, text="Abrir imagen", command=self.open_image).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(toolbar, text="Capturar pantalla", command=self.capture_screen).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(toolbar, text="Analizar", command=self.analyze_current_image).grid(row=0, column=2, padx=(0, 8))
        self.watch_button = ttk.Button(toolbar, text="Vigilar", command=self.toggle_watch)
        self.watch_button.grid(row=0, column=3, padx=(0, 14))

        ttk.Label(toolbar, text="x").grid(row=0, column=4)
        ttk.Entry(toolbar, textvariable=self.x_var, width=6).grid(row=0, column=5, padx=(3, 8))
        ttk.Label(toolbar, text="y").grid(row=0, column=6)
        ttk.Entry(toolbar, textvariable=self.y_var, width=6).grid(row=0, column=7, padx=(3, 8))
        ttk.Label(toolbar, text="ancho").grid(row=0, column=8)
        ttk.Entry(toolbar, textvariable=self.w_var, width=7).grid(row=0, column=9, sticky="w", padx=(3, 8))
        ttk.Label(toolbar, text="alto").grid(row=0, column=10)
        ttk.Entry(toolbar, textvariable=self.h_var, width=7).grid(row=0, column=11, padx=(3, 8))
        ttk.Label(toolbar, text="cada s").grid(row=0, column=12)
        ttk.Entry(toolbar, textvariable=self.interval_var, width=5).grid(row=0, column=13, padx=(3, 8))
        ttk.Label(toolbar, text="umbral").grid(row=0, column=14)
        ttk.Entry(toolbar, textvariable=self.threshold_var, width=6).grid(row=0, column=15, padx=(3, 0))

        body = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        body.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))

        preview_frame = ttk.Frame(body)
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(0, weight=1)
        self.preview_label = ttk.Label(preview_frame, anchor="center")
        self.preview_label.grid(row=0, column=0, sticky="nsew")
        body.add(preview_frame, weight=3)

        side = ttk.Frame(body, padding=(14, 8))
        side.columnconfigure(0, weight=1)
        body.add(side, weight=1)

        self.signal_label = ttk.Label(side, textvariable=self.signal_var, anchor="center", font=("TkDefaultFont", 20, "bold"))
        self.signal_label.grid(row=0, column=0, sticky="ew", pady=(0, 12))

        ttk.Label(side, text="Lectura").grid(row=1, column=0, sticky="w")
        self.detail_text = tk.Text(side, height=13, wrap="word", padx=8, pady=8)
        self.detail_text.grid(row=2, column=0, sticky="nsew", pady=(4, 12))
        side.rowconfigure(2, weight=1)

        warning = (
            "Aviso: esta herramienta solo analiza patrones visuales. "
            "No ejecuta compras y no reemplaza una decision financiera."
        )
        ttk.Label(side, text=warning, wraplength=310, foreground="#6b7280").grid(row=3, column=0, sticky="ew")

        status = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(12, 6))
        status.grid(row=2, column=0, sticky="ew")

        self.bind("<Configure>", lambda _event: self.update_preview())

    def _load_default_image_if_present(self):
        if os.path.exists(DEFAULT_IMAGE):
            self.load_image(DEFAULT_IMAGE)

    def open_image(self):
        path = filedialog.askopenfilename(
            title="Abrir imagen",
            filetypes=[("Imagenes", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Todos", "*.*")],
        )
        if path:
            self.load_image(path)

    def load_image(self, path):
        try:
            self.current_image = Image.open(path).convert("RGB")
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"No pude abrir la imagen:\n{exc}")
            return

        self.status_var.set(f"Imagen cargada: {os.path.basename(path)}")
        self.update_preview()

    def capture_screen(self):
        try:
            bbox = self.get_bbox()
            self.current_image = ImageGrab.grab(bbox=bbox).convert("RGB")
        except ValueError as exc:
            messagebox.showerror(APP_TITLE, str(exc))
            return
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"No pude capturar pantalla:\n{exc}")
            return

        self.status_var.set("Captura tomada.")
        self.update_preview()

    def get_bbox(self):
        try:
            x = max(0, int(float(self.x_var.get())))
            y = max(0, int(float(self.y_var.get())))
            w = max(1, int(float(self.w_var.get())))
            h = max(1, int(float(self.h_var.get())))
        except ValueError as exc:
            raise ValueError("x, y, ancho y alto deben ser numeros.") from exc
        return (x, y, x + w, y + h)

    def get_threshold(self):
        try:
            return max(0.01, min(1.0, float(self.threshold_var.get())))
        except ValueError:
            messagebox.showerror(APP_TITLE, "El umbral debe ser un numero.")
            return 0.18

    def analyze_current_image(self):
        if self.current_image is None:
            messagebox.showinfo(APP_TITLE, "Primero carga una imagen o captura pantalla.")
            return

        if self.analysis_thread and self.analysis_thread.is_alive():
            return

        image = self.current_image.copy()
        threshold = self.get_threshold()
        self.status_var.set("Analizando imagen con PyTorch...")
        self.analysis_thread = threading.Thread(
            target=self._run_analysis,
            args=(image, threshold),
            daemon=True,
        )
        self.analysis_thread.start()

    def _run_analysis(self, image, threshold):
        try:
            result = analyze_trading_image(image, threshold=threshold)
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror(APP_TITLE, str(exc)))
            self.after(0, lambda: self.status_var.set("Analisis fallido."))
            return

        self.after(0, lambda: self.show_result(result))

    def show_result(self, result):
        self.signal_var.set(f"{result.signal}  {result.confidence * 100:.0f}%")
        details = (
            f"Score: {result.score:.3f}\n"
            f"Presion verde: {result.green_pressure:.3f}\n"
            f"Presion roja: {result.red_pressure:.3f}\n"
            f"Momentum linea azul: {result.momentum:.3f}\n"
            f"Cobertura azul: {result.blue_coverage:.4f}\n"
            f"Cobertura verde: {result.green_coverage:.4f}\n"
            f"Cobertura roja: {result.red_coverage:.4f}\n\n"
            f"Motivo: {result.reason}"
        )
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", details)
        self.status_var.set(f"Ultimo analisis: {time.strftime('%H:%M:%S')}")

    def toggle_watch(self):
        self.watch_running = not self.watch_running
        self.watch_button.configure(text="Detener" if self.watch_running else "Vigilar")
        if self.watch_running:
            self.watch_loop()
        elif self.watch_job:
            self.after_cancel(self.watch_job)
            self.watch_job = None

    def watch_loop(self):
        if not self.watch_running:
            return
        self.capture_screen()
        self.analyze_current_image()
        try:
            interval_ms = max(300, int(float(self.interval_var.get()) * 1000))
        except ValueError:
            interval_ms = 2000
            self.interval_var.set("2.0")
        self.watch_job = self.after(interval_ms, self.watch_loop)

    def update_preview(self):
        if self.current_image is None:
            return

        max_width = max(320, self.preview_label.winfo_width() - 16)
        max_height = max(260, self.preview_label.winfo_height() - 16)
        image = self.current_image.copy()
        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        self.preview_image = ImageTk.PhotoImage(image)
        self.preview_label.configure(image=self.preview_image)


def parse_args():
    parser = argparse.ArgumentParser(description="App Tkinter + PyTorch para analizar una pantalla de trading.")
    parser.add_argument("--image", help="Imagen inicial para analizar.")
    return parser.parse_args()


def main():
    args = parse_args()
    app = TradingAssistantApp()
    if args.image:
        app.load_image(args.image)
    app.mainloop()


if __name__ == "__main__":
    main()
