from midiutil import MIDIFile

class Transmitter:
    def __init__(self):
        # midi object
        self.midi = None

        # metadata
        self.time = 0
        self.duration = 2
        self.tempo = 90
        self.volume = 100
        self.num_channel = 0
        self.drone = False

        self.notes_mapping = {
            "C" : 0,
            "C#" : 1,
            "D" : 2,
            "D#" : 3,
            "E" : 4,
            "F" : 5,
            "F#" : 6,
            "G" : 7,
            "G#" : 8,
            "A" : 9,
            "A#" : 10,
            "B" : 11
        }

    # num_tracks is for the number of tracks on the midi file
    # deinterleave is true, removes interleaved notes 
    # remove_duplicates removes dup notes
    # ticks per quaternote is the amount of ticks per quarter note, other common values are 120,240,384, 480
    def config(self, num_tracks=1, remove_duplicates=True, deinterleave=True, ticks_per_quaternote=960):
        self.midi = MIDIFile(numTracks=num_tracks,
                        removeDuplicates=remove_duplicates,
                        deinterleave=deinterleave,
                        ticks_per_quarternote=ticks_per_quaternote)

    # writes tracks to midi file
    # metadata to overwrite existing metadata ig, with metadata provided in dict format
    def write(self, notes, note_metadata, metadata, track_num):
        self.time = 0

        if metadata != None:
            metadata["time"] = self.time
            metadata["duration"] = self.duration
            metadata["tempo"] = self.tempo
            metadata["volume"] = self.volume
            metadata["num_channels"] = self.num_channel

        # track
        self.midi.addTrackName(track=track_num, time=self.time, trackName="base")

        # 81 IS GOATED
        self.midi.addProgramChange(track_num, self.num_channel, self.time, 4)

        # optional. But controls the tempo of midi file
        self.midi.addTempo(track=track_num, time=self.time, tempo=self.tempo)
        song_end = 0
        note_start_times = []
        for idx, note in enumerate(notes):
            meta = note_metadata[idx]
            note_start_time = self.time + meta.get("previous", 0)
            note_start_times.append(note_start_time)
            song_end = max(song_end, note_start_time + meta["duration"])

            if isinstance(note, list):
                for chord_note in note:
                    pitch = self.calculatePitch(chord_note)
                    self.midi.addNote(track=track_num, channel=self.num_channel,
                        pitch=pitch, time=note_start_time,
                        duration=meta["duration"], volume=meta["volume"])
            else:
                pitch = self.calculatePitch(note)
                self.midi.addNote(track=track_num, channel=self.num_channel,
                                pitch=pitch, time=note_start_time,
                                duration=meta["duration"], volume=meta["volume"])

            self.time = note_start_time + meta.get("time", 0)

        if self.drone:
            for idx in range(0, len(note_start_times), 8):
                drone_start = note_start_times[idx]
                next_drone_start = (note_start_times[idx + 8]
                                    if idx + 8 < len(note_start_times)
                                    else song_end)
                self.midi.addNote(track=track_num, channel=self.num_channel,
                                  pitch=self.calculatePitch(self.drone),
                                  time=drone_start,
                                  duration=max(0, next_drone_start - drone_start),
                                  volume=self.volume)

                
    # takes note and returns the pitch
    def calculatePitch(self, note):
        sharp = (len(note) == 3)
        
        if sharp:
            midiCode = self.notes_mapping[note[:2]]
        else:
            midiCode = self.notes_mapping[note[:1]]

        octave = int(note[-1])

        return midiCode + ((octave + 1) * 12)

    # file out
    def save(self, path):
        with open(path, "wb") as output_file:
            self.midi.writeFile(output_file)



        