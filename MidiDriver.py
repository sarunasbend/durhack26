import Avison as a
import Settings
import Transmitter as t
from SenderGUI import SenderGUI

if __name__ == "__main__":
    composer = a.Composer(Settings.KEY, Settings.SCALE_TYPE)
    transmitter = t.Transmitter()
    transmitter.tempo = Settings.TEMPO
    transmitter.drone = Settings.DRONE

    senderGUI = SenderGUI(transmitter, composer)
    senderGUI.run()
