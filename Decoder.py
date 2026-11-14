from Characters import *
from Notes import *
from Permuter import *

class Decoder(object):
    def __init__(self, configuration, scale):
        self.configuration = configuration
        self.scale = scale

        self.characters = Characters()
        self.characters.load_character_set()
        self.notes = Notes()
        self.notes.create_note_table(self.scale, self.configuration.octaves, self.configuration.first_octave)

        self.decoding_table = {}
        self.construct_decoding_table()

    def construct_decoding_table(self):
        permuter = Permuter(self.configuration.cluster_size, self.configuration.octaves, self.configuration.first_octave, self.notes, self.characters)
        self.decoding_table = permuter.construct_table()
        self.decoding_table = {",".join(value): key for key, value in self.decoding_table.items()}

    def decode(self, song):
        output_stream = ""

        cluster = []

        for s in song:
            if len(cluster) < self.configuration.cluster_size:
                cluster.append(s)
                continue
            output_stream += self.decoding_table[",".join(cluster)]
            cluster = [s]
            
        if len(cluster) > 0:
            output_stream += self.decoding_table[",".join(cluster)]

        return output_stream