"""Application entrypoint for the DMF upper-computer simulator."""

from __future__ import annotations

import tkinter as tk

from app_controller import STM32MatrixController


def main() -> None:
    root = tk.Tk()
    STM32MatrixController(root)
    root.mainloop()


if __name__ == "__main__":
    main()
