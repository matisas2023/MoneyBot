import tkinter as tk

from .gui import SignalBotGUI


def main() -> None:
    root = tk.Tk()
    SignalBotGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
