from Characters import *
from Notes import *
from Permuter import *

class Encoder(object):
    def __init__(self, configuration, tokenizer, scale):
        self.configuration = configuration
        self.tokenizer = tokenizer
        self.scale = scale

        self.characters = Characters()
        self.characters.load_character_set()
        self.notes = Notes()
        self.notes.create_note_table(self.scale, self.configuration.octaves, self.configuration.first_octave)

        self.encoding_table = {}
        self.construct_encoding_table()


    def construct_encoding_table(self):
        permuter = Permuter(self.configuration.cluster_size, self.configuration.octaves, self.configuration.first_octave, self.notes, self.characters)
        self.encoding_table = permuter.construct_table()
        

    def encode(self):
        output_stream = []

        stream = self.tokenizer.stream
        for c in stream:
            output_stream += self.encoding_table[c]

        return output_stream