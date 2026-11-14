class Notes(object):
    def __init__(self):
        self.notes = []

    def create_note_table(self, scale, octaves, first_octave=4):
        for o in range(first_octave, first_octave+octaves):
            for note in scale.scale:
                self.notes.append(note.upper() + str(o))