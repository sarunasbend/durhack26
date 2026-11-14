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

        self.note_pattern = [
            "crotchet",
            "crotchet",
            "crotchet",
            "crotchet",
            "quaver",
            "quaver",
            "quaver",
            "quaver",
            "quaver",
            "quaver",
            "quaver",
            "quaver",
            "crotchet",
            "quaver",
            "quaver",
            "crotchet",
            "quaver",
            "quaver",
            "crotchet",
            "quaver",
            "quaver",
            "crotchet",
            "quaver",
            "quaver",
            "crotchet",
            "quaver",
            "quaver",
            "crotchet",
            "quaver",
            "quaver",
            "quaver",
            "quaver"
        ]

        self.volume_pattern = [
            95,
            80,
            72,
            88,
            78,
            70,
            86,
            75,
            50,
            50,
            50
        ]

    def convert_to_meta(self, pattern):
        if pattern == "quaver":
            return {
                "duration": 0.5,
                "time": 0.5
            }
        if pattern == "crotchet":
            return {
                "duration": 2,
                "time": 1
            }


    def construct_encoding_table(self):
        permuter = Permuter(self.configuration.cluster_size, self.configuration.octaves, self.configuration.first_octave, self.notes, self.characters)
        self.encoding_table = permuter.construct_table()
        

    def encode(self):
        output_stream = []
        metadata_stream = []

        stream = self.tokenizer.stream
        current_note_i = 0
        current_volume_i = 0

        previous_time = 0

        for c in stream:
            output_stream += self.encoding_table[c]
            for i in range(self.configuration.cluster_size):
                current_note = self.note_pattern[current_note_i]
                current_volume = self.volume_pattern[current_volume_i]
                current_note_i += 1
                current_volume_i += 1
                if current_note_i >= len(self.note_pattern):
                    current_note_i = 0
                if current_volume_i >= len(self.volume_pattern):
                    current_volume_i = 0
                meta = self.convert_to_meta(current_note)
                meta["volume"] = current_volume
                meta["previous"] = previous_time
                previous_time = meta["time"]
                metadata_stream.append(meta)

        return output_stream, metadata_stream