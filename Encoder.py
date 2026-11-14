class Characters(object):
    def __init__(self):
        self.characters = []

    def load_character_set(self,c_set="reduced"):
        if c_set == "reduced":
            self.characters = list(
                "abcdefghijklmnopqrstuvwxyz"
                "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                "0123456789"
                " .,!?;:'\"()-\n"
            )

class Notes(object):
    def __init__(self):
        self.notes = []

    def create_note_table(self, scale, octaves, first_octave=4):
        for o in range(first_octave, first_octave+octaves):
            for note in scale.scale:
                self.notes.append(note.upper() + str(o))



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

    def add_note_permutations(self, cluster, note):
        if cluster <= 1:
            return [[note]]

        permutations = []

        for next_note in self.notes.notes:
            for suffix in self.add_note_permutations(cluster - 1, next_note):
                permutations.append([note] + suffix)

        return permutations

    def construct_encoding_table(self):
        self.permutations = []
        for note in self.notes.notes:
            self.permutations.extend(
                self.add_note_permutations(self.configuration.cluster_size, note)
            )

        for c in range(len(self.characters.characters)):
            key = self.characters.characters[c]
            self.encoding_table[key] = self.permutations[c]
        

    def encode(self):
        output_stream = []

        stream = self.tokenizer.stream
        for c in stream:
            output_stream += self.encoding_table[c]

        return output_stream