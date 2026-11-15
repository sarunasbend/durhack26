import Avison as a
import tkinter as tk
import Transmitter as t
import Settings
from ReceiverGUI import *
from SenderGUI import *
from Front import Front

def transmit(composer):
    print("Setting up Transmitter")
    transmitter = t.Transmitter()
    transmitter.tempo = Settings.TEMPO
    transmitter.drone = Settings.DRONE

    sender = SenderGUI(transmitter=transmitter, encoder=composer)
    sender.run()

    # reciever = ReceiverGUI(transmitter=transmitter, encoder=composer)
    # reciever.run()

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

    canvas.create_text(220, 75, text="Planet Symphony", fill="#f4f6ff", font=("Segoe UI", 21, "bold"))
    canvas.create_text(220, 108, text="CHOOSE YOUR MISSION", fill="#9cafd8", font=("Segoe UI", 9, "bold"))

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
    receive_button = tk.Button(
        root, text="RECEIVE", command=lambda: receive(composer),
        bg="#1b2b50", fg="#e1eaff", activebackground="#1e2536", activeforeground="white",
        **button_options,
    )
    canvas.create_window(220, 177, window=transmit_button, width=190, height=46)
    canvas.create_window(220, 236, window=receive_button, width=190, height=46)

    root.mainloop()

if __name__ == "__main__":
    message = "I LOVE durhack26!"

    composer = a.Composer(Settings.KEY, Settings.SCALE_TYPE)

    create_gui(composer)

    # encoded, metadata = composer.encode_message(message)
    # transmitter = t.Transmitter()
    # transmitter.config()

    # transmitter.tempo = Settings.TEMPO
    # transmitter.drone = Settings.DRONE
    
    # transmitter.write(encoded, metadata, None, 0)
    # transmitter.save("out.mid")

    # front = Front()
    # front.createWindow()
    # front.playMIDI("out.mid")

    # decoded = composer.decode_message(encoded)
    # decoded = ""
    # decoder = composer.stream_decode()
    # decoder.begin_decode()
    # for i in encoded:
    #     decoder.add_to_stream(i)
    # decoded = decoder.stream_decoded
    # print(decoded)

    # message = message.strip()
    # decoded = decoded.strip()

    # if message == decoded:
    #     print("No Error")
    # else:
    #     print("Some Error")
    #     for i, (expected, actual) in enumerate(zip(message, decoded)):
    #         if expected != actual:
    #             print(f"Discrepancy at {i}: {expected!r} != {actual!r}")
    #     if len(message) != len(decoded):
    #         print(f"Length mismatch: expected {len(message)}, got {len(decoded)}")