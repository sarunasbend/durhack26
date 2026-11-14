class Permuter(object):
    def __init__(self, clusters, octaves, starting_octave, notes, characters):
        self.clusters = clusters
        self.octaves = octaves
        self.starting_octave = starting_octave
        self.notes = notes
        self.characters = characters

        self.table = {}

    def add_note_permutations(self, cluster, note):
            if cluster <= 1:
                return [[note]]
    
            permutations = []
    
            for next_note in self.notes.notes:
                for suffix in self.add_note_permutations(cluster - 1, next_note):
                    permutations.append([note] + suffix)
    
            return permutations
    
    def construct_table(self):
        permutations = []
        for note in self.notes.notes:
            permutations.extend(
                self.add_note_permutations(self.clusters, note)
            )

        for c in range(len(self.characters.characters)):
            key = self.characters.characters[c]
            self.table[key] = permutations[c]

        return self.table