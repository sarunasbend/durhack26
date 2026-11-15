import Avison as a
import tkinter as tk
import Transmitter as t
import Settings
from ReceiverGUI import *
from SenderGUI import *
import tkinter.font as tkFont

def transmit(composer):
    print("Setting up Transmitter")
    transmitter = t.Transmitter()
    transmitter.tempo = Settings.TEMPO
    transmitter.drone = Settings.DRONE

    sender = SenderGUI(transmitter=transmitter, encoder=composer)
    sender.run()

def receive(composer):
    print("Setting up Receiver")
    transmitter = t.Transmitter()
    transmitter.tempo = Settings.TEMPO
    transmitter.drone = Settings.DRONE
    
    reciever = ReceiverGUI(transmitter=transmitter, encoder=composer)
    reciever.run()

def create_gui(composer):
    root = tk.Tk()
    root.title("DURHACK 2026")
    root.geometry("440x320")
    root.resizable(False, False)
    root.configure(bg="#080d22")

    canvas = tk.Canvas(root, width=440, height=320, bg="#080d22", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)

    # Draw a simple starfield directly on the canvas, so no image assets are needed.
    stars = [
        (22, 32, 2), (70, 83, 1), (119, 27, 1), (178, 57, 2), (244, 22, 1),
        (312, 61, 2), (405, 34, 1), (34, 144, 1), (92, 207, 2), (151, 126, 1),
        (273, 113, 1), (391, 164, 2), (27, 254, 1), (130, 286, 2), (205, 246, 1),
        (300, 284, 1), (367, 251, 2), (423, 211, 1), (225, 160, 1), (340, 20, 1),
    ]
    for x, y, size in stars:
        canvas.create_oval(x, y, x + size, y + size, fill="#faffe6", outline="")

    big_font = tkFont.Font(family="consolas", size=26, weight="bold")
    small_font = tkFont.Font(family="consolas", size=15, weight="normal")

    canvas.create_text(220, 75, text="Planet Symphony", fill="#f4f6ff", font=big_font)
    canvas.create_text(220, 108, text="CHOOSE YOUR MISSION", fill="#9cafd8", font=small_font)

    button_options = {
        "width": 18,
        "font": ("Segoe UI", 11, "bold"),
        "relief": tk.FLAT,
        "bd": 0,
        "cursor": "hand2",
    }
    transmit_button = tk.Button(
        root, text="TRANSMIT", command=lambda: transmit(composer),
        bg="#586fff", fg="white", activebackground="#788aff", activeforeground="white",
        **button_options,
    )

    transmit_button['font'] = small_font

    receive_button = tk.Button(
        root, text="RECEIVE", command=lambda: receive(composer),
        bg="#1b2b50", fg="#e1eaff", activebackground="#1e2536", activeforeground="white",
        **button_options,
    )

    receive_button['font'] = small_font

    canvas.create_window(220, 177, window=transmit_button, width=190, height=46)
    canvas.create_window(220, 236, window=receive_button, width=190, height=46)

    root.mainloop()

if __name__ == "__main__":
    message = "I LOVE durhack26!"

    composer = a.Composer(Settings.KEY, Settings.SCALE_TYPE)

    create_gui(composer)