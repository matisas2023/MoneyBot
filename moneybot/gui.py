import threading
import tkinter as tk
from tkinter import messagebox, ttk, TclError

from .auth import launch_google_auth_and_get_ssid
from .config import (
    BotConfig,
    DEFAULT_API_RETRY_DELAY_SEC,
    DEFAULT_CANDLES_LIMIT,
    DEFAULT_CHECK_INTERVAL_SEC,
    DEFAULT_FOREX_PAIRS,
    DEFAULT_TIMEFRAME_SEC,
)
from .engine import run_signal_bot


class SignalBotGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Pocket Option Signal Bot")
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None

        self.auth_method_var = tk.StringVar(value="google")
        self.email_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.ssid_var = tk.StringVar()
        self.pairs_var = tk.StringVar(value=",".join(DEFAULT_FOREX_PAIRS))
        self.timeframe_var = tk.StringVar(value=str(DEFAULT_TIMEFRAME_SEC))
        self.limit_var = tk.StringVar(value=str(DEFAULT_CANDLES_LIMIT))
        self.interval_var = tk.StringVar(value=str(DEFAULT_CHECK_INTERVAL_SEC))
        self.retry_var = tk.StringVar(value=str(DEFAULT_API_RETRY_DELAY_SEC))

        self._build_ui()

    def _build_ui(self) -> None:
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        def row(label: str, widget, r: int):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, sticky="ew", pady=3)

        frm.columnconfigure(1, weight=1)

        row("Auth method", ttk.Combobox(frm, textvariable=self.auth_method_var, values=["google", "password"], state="readonly"), 0)
        row("Email", ttk.Entry(frm, textvariable=self.email_var), 1)
        row("Password", ttk.Entry(frm, textvariable=self.password_var, show="*"), 2)
        row("SSID", ttk.Entry(frm, textvariable=self.ssid_var), 3)
        row("Pairs (comma)", ttk.Entry(frm, textvariable=self.pairs_var), 4)
        row("Timeframe sec", ttk.Entry(frm, textvariable=self.timeframe_var), 5)
        row("Candles limit", ttk.Entry(frm, textvariable=self.limit_var), 6)
        row("Check interval sec", ttk.Entry(frm, textvariable=self.interval_var), 7)
        row("Retry delay sec", ttk.Entry(frm, textvariable=self.retry_var), 8)

        btns = ttk.Frame(frm)
        btns.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        ttk.Button(btns, text="Google Auth", command=self.google_auth).pack(side="left", padx=4)
        ttk.Button(btns, text="Start", command=self.start_bot).pack(side="left", padx=4)
        ttk.Button(btns, text="Stop", command=self.stop_bot).pack(side="left", padx=4)

        self.log_text = tk.Text(frm, height=18, wrap="word")
        self.log_text.grid(row=10, column=0, columnspan=2, sticky="nsew")
        self.log_menu = tk.Menu(self.root, tearoff=0)
        self.log_menu.add_command(label="Копіювати", command=self.copy_selected_log)
        self.log_menu.add_command(label="Копіювати все", command=self.copy_all_logs)
        self.log_text.bind("<Control-c>", self.copy_selected_log)
        self.log_text.bind("<Button-3>", self.show_log_context_menu)
        frm.rowconfigure(10, weight=1)

    def log(self, message: str) -> None:
        print(message, flush=True)
        self.root.after(0, lambda m=message: (self.log_text.insert("end", m + "\n"), self.log_text.see("end")))

    def build_config(self) -> BotConfig:
        pairs = [x.strip().upper() for x in self.pairs_var.get().split(",") if x.strip()]
        return BotConfig(
            auth_method=self.auth_method_var.get().strip().lower(),
            email=self.email_var.get().strip(),
            password=self.password_var.get(),
            google_ssid=self.ssid_var.get().strip(),
            pairs=pairs or DEFAULT_FOREX_PAIRS,
            timeframe_sec=int(self.timeframe_var.get()),
            candles_limit=int(self.limit_var.get()),
            check_interval_sec=int(self.interval_var.get()),
            api_retry_delay_sec=int(self.retry_var.get()),
        )

    def google_auth(self) -> None:
        try:
            token = launch_google_auth_and_get_ssid(self.log)
            self.ssid_var.set(token)
            self.auth_method_var.set("google")
        except Exception as error:
            messagebox.showerror("Google auth error", str(error))

    def start_bot(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        config = self.build_config()
        self.stop_event.clear()

        def runner():
            try:
                run_signal_bot(config, self.stop_event, self.log)
            except Exception as error:
                self.log(f"[КРИТИЧНА ПОМИЛКА] {error}")

        self.worker = threading.Thread(target=runner, daemon=True)
        self.worker.start()

    def show_log_context_menu(self, event) -> str:
        self.log_text.focus_set()
        self.log_menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def copy_selected_log(self, event=None) -> str:
        try:
            selected = self.log_text.selection_get()
        except TclError:
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(selected)
        return "break"

    def copy_all_logs(self) -> None:
        content = self.log_text.get("1.0", "end-1c")
        if not content:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)

    def stop_bot(self) -> None:
        self.stop_event.set()
        self.log("Бот зупиняється...")
