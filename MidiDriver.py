import Avison as a
import tkinter as tk
import Transmitter as t
from ReceiverGUI import *
from Front import Front
from SenderGUI import SenderGUI

if __name__ == "__main__":
    composer = a.Composer("d", "major")
    transmitter = t.Transmitter()

    senderGUI = SenderGUI(transmitter, composer)
    senderGUI.run()

