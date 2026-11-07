"""Daily real-experiment operator entry; no simulated observations or motion."""

from __future__ import annotations

import tkinter as tk

from app_controller import STM32MatrixController


def main() -> None:
    root = tk.Tk()
    STM32MatrixController(root, operator_only=True)
    root.mainloop()


if __name__ == "__main__":
    main()
