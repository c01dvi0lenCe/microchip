"""Independent research UI; shares operator layout and never opens real serial."""
import tkinter as tk
from app_controller import STM32MatrixController


def main():
    root=tk.Tk()
    STM32MatrixController(root,simulation_only=True)
    root.mainloop()


if __name__=='__main__':main()
