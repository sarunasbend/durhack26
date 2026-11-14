import os
import pygame

# ignore this if not on linux cuz its 
os.environ["SDL_SOUNDFONTS"] = "/usr/share/sounds/sf2/FluidR3_GM.sf2"

class Front:
    def __init__(self):
        self.screen = None
        self.clock = pygame.time.Clock()

    def createWindow(self):
        pygame.init()
        self.screen = pygame.display.set_mode((500, 500))

    def playMIDI(self, path: str):
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()

            while pygame.mixer.music.get_busy():
                print("PLAYING MIDI")

        except Exception as e:
            print(f"MIDI ERROR: {e}")
