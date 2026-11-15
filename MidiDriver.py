import Avison as a
import Settings
import Transmitter as t
from SenderGUI import SenderGUI
from ReceiverGUI import ReceiverGUI

# testing file
if __name__ == "__main__":
    composer = a.Composer(Settings.KEY, Settings.SCALE_TYPE)
    transmitter = t.Transmitter()
    transmitter.tempo = Settings.TEMPO
    transmitter.drone = Settings.DRONE

    reciever = ReceiverGUI(transmitter=transmitter, encoder=composer)
    reciever.run()

    