from Transmitter import Transmitter
from Front import Front

if __name__ == "__main__":
    midi = Transmitter()

    notes = ["C4", "D4", "E4", "E3", "E6"]

    midi.config()
    midi.write(notes, None, 0)
    midi.save("out.mid")

    front = Front()
    front.createWindow()
    front.playMIDI("out.mid")

    
