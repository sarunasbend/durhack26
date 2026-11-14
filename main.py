import Avison as a
import tkinter as tk
import Transmitter as t
from ReceiverGUI import *
from Front import Front

def transmit(composer):
    print("Setting up Transmitter")

def receive(composer):
    print("Setting up Receiver")
    rGUI = ReceiverGUI(composer)

def create_gui(composer):
    root = tk.Tk()
    root.title("DURHACK 2026")
    root.geometry("220x120")
    root.resizable(False, False)

    frame = tk.Frame(root, padx=20, pady=20)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Button(frame, text="Transmit", width=16, command=lambda: transmit(composer)).pack(pady=(0, 10))
    tk.Button(frame, text="Receive", width=16, command=lambda: receive(composer)).pack()

    root.mainloop()

if __name__ == "__main__":
    message = "We are Ad Libertum T-Shirt, thank you for watching our demo!"

    composer = a.Composer("c", "minor-pentatonic")

    # create_gui(composer)

    encoded, metadata = composer.encode_message(message)
    f = open("debug_encode.txt", "w")
    f.write(",".join(encoded))
    f.close()

    transmitter = t.Transmitter()
    transmitter.config()

    transmitter.tempo = 200
    # transmitter.drone = "C2"
    
    transmitter.write(encoded, metadata, None, 0)
    transmitter.save("out.mid")

    front = Front()
    front.createWindow()
    front.playMIDI("out.mid")

    decoded = composer.decode_message(encoded)
    decoded = ""
    decoder = composer.stream_decode()
    decoder.begin_decode()
    for i in encoded:
        decoder.add_to_stream(i)
    decoded = decoder.stream_decoded
    print(decoded)

    message = message.strip()
    decoded = decoded.strip()

    if message == decoded:
        print("No Error")
    else:
        print("Some Error")
        for i, (expected, actual) in enumerate(zip(message, decoded)):
            if expected != actual:
                print(f"Discrepancy at {i}: {expected!r} != {actual!r}")
        if len(message) != len(decoded):
            print(f"Length mismatch: expected {len(message)}, got {len(decoded)}")