import os
import math
import pygame
import Settings
from Transmitter import Transmitter
from Avison import Composer
from tune_island import TuneIsland

try:
    from PIL import Image, ImageSequence
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

class SenderGUI:
    def __init__(self, transmitter: Transmitter, encoder: Composer):
        self.transmitter = transmitter
        self.encoder = encoder
        self.island = None
        self.path = "out.mid"

        pygame.init()
        pygame.mixer.init()

        self.width = 1024
        self.height = 800
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Sender")

        self.heading_font = pygame.font.Font(None, 48)
        self.text_font = pygame.font.Font(None, 28)
        self.button_font = pygame.font.Font(None, 32)

        current_dir = os.path.dirname(os.path.abspath(__file__))

        bg_path = os.path.join(current_dir, "assets", "stars.gif")
        if not os.path.exists(bg_path):
            bg_path = os.path.join("assets", "stars.gif")

        self.bg_image = None
        if os.path.exists(bg_path):
            try:
                self.bg_image = pygame.image.load(bg_path)
                self.bg_image = pygame.transform.scale(self.bg_image, (self.width, self.height))
            except Exception as e:
                print(e)
                self.bg_image = None

        self._ensure_planet_frames(current_dir)

        self.planet_frames = []
        self.planet_frame_duration = 100
        self.current_planet_frame = 0
        self.last_frame_time = pygame.time.get_ticks()

        self.stars_frames = []
        self.stars_frame_duration = 100
        self.current_stars_frame = 0
        self.last_stars_frame_time = pygame.time.get_ticks()

        frames_dir = os.path.join(current_dir, "assets", "planet_frames")
        if not os.path.exists(frames_dir):
            frames_dir = os.path.join("assets", "planet_frames")

        duration_file = os.path.join(frames_dir, "duration.txt")
        if os.path.exists(duration_file):
            try:
                with open(duration_file, "r") as df:
                    self.planet_frame_duration = int(df.read().strip())
            except Exception:
                self.planet_frame_duration = 100

        if os.path.isdir(frames_dir):
            frame_files = sorted([
                f for f in os.listdir(frames_dir)
                if f.lower().endswith((".png", ".jpg"))
            ])
            for f in frame_files:
                try:
                    surf = pygame.image.load(os.path.join(frames_dir, f)).convert_alpha()
                    self.planet_frames.append(surf)
                except Exception as e:
                    print(f"Failed to load frame {f}: {e}")

        if not self.planet_frames:
            gif_path = os.path.join(current_dir, "assets", "planet.gif")
            if not os.path.exists(gif_path):
                gif_path = os.path.join("assets", "planet.gif")

            if os.path.exists(gif_path):
                if HAS_PIL:
                    try:
                        pil_gif = Image.open(gif_path)
                        self.planet_frame_duration = pil_gif.info.get("duration", 100) or 100
                        for frame in ImageSequence.Iterator(pil_gif):
                            rgba_frame = frame.convert("RGBA")
                            data = rgba_frame.tobytes()
                            size = rgba_frame.size
                            if hasattr(pygame.image, "frombytes"):
                                surf = pygame.image.frombytes(data, size, "RGBA")
                            else:
                                surf = pygame.image.fromstring(data, size, "RGBA")
                            self.planet_frames.append(surf.convert_alpha())
                    except Exception as e:
                        print(f"Failed to load planet.gif with PIL: {e}")

                if not self.planet_frames:
                    try:
                        single_frame = pygame.image.load(gif_path).convert_alpha()
                        self.planet_frames = [single_frame]
                    except Exception as e:
                        print(f"Failed to load planet.gif with pygame: {e}")

        star_frames_dir = os.path.join(current_dir, "assets", "star_frames")
        if not os.path.exists(star_frames_dir):
            star_frames_dir = os.path.join("assets", "star_frames")

        star_duration_file = os.path.join(star_frames_dir, "duration.txt")
        if os.path.exists(star_duration_file):
            try:
                with open(star_duration_file, "r") as df:
                    self.stars_frame_duration = int(df.read().strip())
            except Exception:
                self.stars_frame_duration = 100

        if os.path.isdir(star_frames_dir):
            frame_files = sorted([
                f for f in os.listdir(star_frames_dir)
                if f.lower().endswith((".png", ".jpg"))
            ])
            for f in frame_files:
                try:
                    surf = pygame.image.load(os.path.join(star_frames_dir, f)).convert_alpha()
                    surf = pygame.transform.scale(surf, (self.width, self.height))
                    self.stars_frames.append(surf)
                except Exception as e:
                    print(f"Failed to load frame {f}: {e}")

        if not self.stars_frames:
            gif_path = os.path.join(current_dir, "assets", "stars.gif")
            if not os.path.exists(gif_path):
                gif_path = os.path.join("assets", "stars.gif")

            if os.path.exists(gif_path):
                if HAS_PIL:
                    try:
                        pil_gif = Image.open(gif_path)
                        self.stars_frame_duration = pil_gif.info.get("duration", 100) or 100
                        for frame in ImageSequence.Iterator(pil_gif):
                            rgba_frame = frame.convert("RGBA")
                            data = rgba_frame.tobytes()
                            size = rgba_frame.size
                            if hasattr(pygame.image, "frombytes"):
                                surf = pygame.image.frombytes(data, size, "RGBA")
                            else:
                                surf = pygame.image.fromstring(data, size, "RGBA")
                            surf = pygame.transform.scale(surf.convert_alpha(), (self.width, self.height))
                            self.stars_frames.append(surf)
                    except Exception as e:
                        print(f"Failed to load stars.gif with PIL: {e}")

                if not self.stars_frames:
                    try:
                        single_frame = pygame.image.load(gif_path).convert_alpha()
                        single_frame = pygame.transform.scale(single_frame, (self.width, self.height))
                        self.stars_frames = [single_frame]
                    except Exception as e:
                        print(f"Failed to load stars.gif with pygame: {e}")

        self.planet_radius = 150
        self.planet_x = float(self.width // 2)
        self.planet_y = float(self.height // 2)

        self.is_dragging = False
        self.drag_offset_x = 0.0
        self.drag_offset_y = 0.0
        self.is_hovered = False
        self.glow_alpha = 0.0

        self.scene = "planet"
        self.green_color = (34, 139, 34)
        self.transition_start_time = 0
        self.transition_duration = 750

        self._running = True

    def _ensure_planet_frames(self, current_dir):
        gif_path = os.path.join(current_dir, "assets", "planet.gif")
        if not os.path.exists(gif_path):
            gif_path = os.path.join("assets", "planet.gif")

        frames_dir = os.path.join(current_dir, "assets", "planet_frames")
        if not os.path.exists(frames_dir):
            frames_dir = os.path.join("assets", "planet_frames")

        os.makedirs(frames_dir, exist_ok=True)
        existing = [f for f in os.listdir(frames_dir) if f.lower().endswith((".png", ".jpg"))]

        needs_generation = not existing
        if not needs_generation and os.path.exists(gif_path):
            try:
                first_frame = os.path.join(frames_dir, existing[0])
                if os.path.getmtime(gif_path) > os.path.getmtime(first_frame):
                    needs_generation = True
            except Exception:
                pass

        if needs_generation and os.path.exists(gif_path) and HAS_PIL:
            try:
                im = Image.open(gif_path)
                dur = im.info.get("duration", 100) or 100
                with open(os.path.join(frames_dir, "duration.txt"), "w") as df:
                    df.write(str(dur))

                for old in existing:
                    try:
                        os.remove(os.path.join(frames_dir, old))
                    except Exception:
                        pass

                for i, frame in enumerate(ImageSequence.Iterator(im)):
                    rgba = frame.convert("RGBA")
                    rgba.save(os.path.join(frames_dir, f"frame_{i:03d}.png"), "PNG")
                print(f"[SenderGUI] Auto-generated {im.n_frames} frames from planet.gif (duration: {dur}ms)")
            except Exception as e:
                print(f"[SenderGUI] Failed to auto-generate frames with PIL: {e}")

    def _generate_midi(self, notes, metadata):
        self.transmitter.tempo = Settings.TEMPO
        self.transmitter.drone = Settings.DRONE

        self.transmitter.config()
        self.transmitter.write(notes, metadata, None, 0)
        self.transmitter.save(self.path)

    def _transmit(self, blocking=False):
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(self.path)
            pygame.mixer.music.play()
            pygame.mixer.music.set_volume(0.2)

            if blocking:
                while pygame.mixer.music.get_busy():
                    for event in pygame.event.get():
                        if event.type == pygame.QUIT:
                            pygame.quit()
                            return
        except Exception as e:
            print(f"MIDI ERROR: {e}")

    def _update_hover(self):
        if self.scene != "planet":
            self.is_hovered = False
            self.glow_alpha = 0.0
            return

        mx, my = pygame.mouse.get_pos()
        dist = math.hypot(mx - self.planet_x, my - self.planet_y)
        self.is_hovered = (dist <= self.planet_radius)

        if self.is_hovered:
            self.glow_alpha = min(255.0, self.glow_alpha + 35.0)
        else:
            self.glow_alpha = max(0.0, self.glow_alpha - 25.0)

    def _start_planet_transition(self):
        self.scene = "transitioning"
        self.transition_start_time = pygame.time.get_ticks()
        self.is_hovered = False
        self.glow_alpha = 0.0

    def _draw_planet_glow(self, center_pos):
        if self.glow_alpha <= 0:
            return

        factor = self.glow_alpha / 255.0
        radius = self.planet_radius
        padding = 24
        glow_size = (radius + padding) * 2
        glow_surf = pygame.Surface((glow_size, glow_size), pygame.SRCALPHA)
        center = (glow_size // 2, glow_size // 2)

        for r in range(padding, 0, -2):
            intensity = (1.0 - (r / padding)) ** 1.8
            alpha = int(factor * 110 * intensity)
            if alpha > 0:
                pygame.draw.circle(glow_surf, (240, 245, 255, alpha), center, radius + r, width=2)

        outline_alpha = int(factor * 255)
        pygame.draw.circle(glow_surf, (255, 255, 255, outline_alpha), center, radius, width=3)
        pygame.draw.circle(glow_surf, (255, 255, 255, int(factor * 180)), center, radius + 1, width=2)
        pygame.draw.circle(glow_surf, (255, 255, 255, int(factor * 160)), center, radius - 1, width=2)

        self.screen.blit(glow_surf, glow_surf.get_rect(center=center_pos))

    def _draw_background(self):
        if self.stars_frames:
            now = pygame.time.get_ticks()
            if now - self.last_stars_frame_time >= self.stars_frame_duration:
                steps = (now - self.last_stars_frame_time) // self.stars_frame_duration
                self.current_stars_frame = (self.current_stars_frame + steps) % len(self.stars_frames)
                self.last_stars_frame_time = now - ((now - self.last_stars_frame_time) % self.stars_frame_duration)
            self.screen.blit(self.stars_frames[self.current_stars_frame], (0, 0))
        elif self.bg_image:
            self.screen.blit(self.bg_image, (0, 0))
        else:
            self.screen.fill((20, 20, 35))

    def _draw_transition(self):
        elapsed = pygame.time.get_ticks() - self.transition_start_time
        p = min(1.0, elapsed / self.transition_duration)

        self._draw_background()

        if self.planet_frames:
            current_frame = self.planet_frames[self.current_planet_frame]
            scale = 1.0 + (p ** 2.2) * 8.0
            orig_w = current_frame.get_width()
            orig_h = current_frame.get_height()
            zoomed_w = max(1, int(orig_w * scale))
            zoomed_h = max(1, int(orig_h * scale))

            zoomed_surf = pygame.transform.scale(current_frame, (zoomed_w, zoomed_h))
            zoomed_rect = zoomed_surf.get_rect(center=(int(self.planet_x), int(self.planet_y)))
            self.screen.blit(zoomed_surf, zoomed_rect)

        flash_alpha = min(255, int(255 * (p ** 1.3)))
        flash_surf = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        flash_surf.fill((255, 255, 255, flash_alpha))
        self.screen.blit(flash_surf, (0, 0))

        if p >= 1.0:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.island = TuneIsland(composer=self.encoder, tempo=Settings.TEMPO, latency=None)
            self.scene = "island"
            self.white_fade_start = pygame.time.get_ticks()

    def _draw(self):
        if self.scene == "transitioning":
            self._draw_transition()
            pygame.display.flip()
            return

        self._update_hover()

        self._draw_background()

        planet_pos = (int(self.planet_x), int(self.planet_y))
        self._draw_planet_glow(planet_pos)

        if self.planet_frames:
            now = pygame.time.get_ticks()
            if now - self.last_frame_time >= self.planet_frame_duration:
                steps = (now - self.last_frame_time) // self.planet_frame_duration
                self.current_planet_frame = (self.current_planet_frame + steps) % len(self.planet_frames)
                self.last_frame_time = now - ((now - self.last_frame_time) % self.planet_frame_duration)

            current_frame = self.planet_frames[self.current_planet_frame]
            planet_rect = current_frame.get_rect(center=planet_pos)
            self.screen.blit(current_frame, planet_rect)

            if self.glow_alpha > 0:
                rim_surf = pygame.Surface((self.planet_radius * 2 + 6, self.planet_radius * 2 + 6), pygame.SRCALPHA)
                rim_center = (self.planet_radius + 3, self.planet_radius + 3)
                rim_alpha = int((self.glow_alpha / 255.0) * 220)
                pygame.draw.circle(rim_surf, (255, 255, 255, rim_alpha), rim_center, self.planet_radius, width=2)
                self.screen.blit(rim_surf, rim_surf.get_rect(center=planet_pos))

        pygame.display.flip()

    def run(self):
        clock = pygame.time.Clock()

        while self._running:
            if self.scene == "island":
                dt = min(clock.tick(60) / 1000.0, 0.05)
                for event in pygame.event.get():
                    if not self.island.handle_event(event):
                        self._running = False

                self.island.update(dt)
                self.island.draw()

                if hasattr(self, "white_fade_start"):
                    fade_elapsed = pygame.time.get_ticks() - self.white_fade_start
                    if fade_elapsed < 300:
                        alpha = int(255 * (1.0 - fade_elapsed / 300.0))
                        flash_surf = pygame.Surface((self.island.win_w, self.island.win_h), pygame.SRCALPHA)
                        flash_surf.fill((255, 255, 255, alpha))
                        self.island.screen.blit(flash_surf, (0, 0))
                    else:
                        del self.white_fade_start

                pygame.display.flip()
            else:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._running = False

                    elif event.type == pygame.MOUSEBUTTONDOWN:
                        if event.button == 1:
                            if self.scene == "planet":
                                mx, my = event.pos
                                if math.hypot(mx - self.planet_x, my - self.planet_y) <= self.planet_radius:
                                    self._start_planet_transition()

                self._draw()
                clock.tick(60)

        if self.island:
            self.island.stop_playback()
        pygame.quit()