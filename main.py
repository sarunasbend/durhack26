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
    message = "To the red country and part of the gray country of Oklahoma, the last rains came gently, and they did not cut the scarred earth. The plows crossed and recrossed the rivulet marks. The last rains lifted the corn quickly and scattered weed colonies and grass along the sides of the roads so that the gray country and the dark red country began to disappear under a green cover. In the last part of May the sky grew pale and the clouds that had hung in high puffs for so long in the spring were dissipated. The sun flared down on the growing corn day after day until a line of brown spread along the edge of each green bayonet. The clouds appeared, and went away, and in a while they did not try any more. The weeds grew darker green to protect themselves, and they did not spread any more. The surface of the earth crusted, a thin hard crust, and as the sky became pale, so the earth became pale, pink in the red country and white in the gray country."

    composer = a.Composer("d", "major")

    # create_gui(composer)

    encoded = composer.encode_message(message)
    f = open("debug_encode.txt", "w")
    f.write(",".join(encoded))
    f.close()

    transmitter = t.Transmitter()
    transmitter.config()
    
    transmitter.write(encoded, None, 0)
    transmitter.save("out.mid")

    front = Front()
    front.createWindow()
    front.playMIDI("out.mid")

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