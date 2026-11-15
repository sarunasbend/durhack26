# What the sender plays. The sender (main.py, MidiDriver.py) and the receiver's
# training code (training/common.py) all read these, so they cannot drift apart.
#
# The receiver's model only understands the settings it was trained on. After
# changing anything here, or the instrument in Transmitter.write, record new
# takes and retrain (see training/README.md).

KEY = 'f#'
SCALE_TYPE = 'major-pentatonic'
TEMPO = 200
DRONE = 'F#2'   # False for no drone
