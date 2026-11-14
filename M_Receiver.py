import math
import threading
import time
from collections import deque
import numpy as np
import sounddevice as sd

class M_Receiver:
    def __init__(self, sample_rate=22050, blocksize=1024, max_history=500):
        self.sample_rate = sample_rate
        self.blocksize = blocksize
        
        # Thread-safe history storage (keeps the last `max_history` entries)
        self._history = deque(maxlen=max_history)
        
        self._stream = None
        self._lock = threading.Lock()
        self._is_running = False

    def _frequency_to_note(self, freq):
        """Convert frequency in Hz to the closest musical note name."""
        if freq < 40 or freq > 2000:
            return None
        
        A4 = 440.0
        C0 = A4 * (2 ** (-4.75))
        h = round(12 * math.log2(freq / C0))
        
        octave = h // 12
        n = h % 12
        notes = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        return f"{notes[n]}{octave}"

    def _audio_callback(self, indata, frames, time_info, status):
        """Fast non-blocking audio callback recording detections to history."""
        if status:
            return
        
        audio_data = indata[:, 0]
        
        # Volume gate to filter out room noise
        rms = np.sqrt(np.mean(audio_data**2))
        if rms < 0.015:
            return
        
        # Center the signal around zero and compute autocorrelation
        signal = audio_data - np.mean(audio_data)
        corr = np.correlate(signal, signal, mode='full')
        corr = corr[len(corr)//2:]
        
        min_lag = int(self.sample_rate / 1000)
        max_lag = int(self.sample_rate / 60)
        
        if max_lag >= len(corr):
            return
            
        search_range = corr[min_lag:max_lag]
        if len(search_range) == 0:
            return
            
        peak_idx = np.argmax(search_range) + min_lag
        freq = self.sample_rate / peak_idx
        
        note = self._frequency_to_note(freq)
        if note:
            # Create a structured record for the note
            entry = {
                "note": note,
                "frequency": freq,
                "timestamp": time.time()
            }
            
            # Safely append to the shared history list
            with self._lock:
                self._history.append(entry)

    def start(self):
        """Starts the audio listener in a background thread."""
        if self._is_running:
            return
        
        self._is_running = True
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            blocksize=self.blocksize,
            channels=1,
            callback=self._audio_callback
        )
        self._stream.start()
        print("Receiver listener started.")

    def stop(self):
        """Stops the audio listener."""
        if not self._is_running:
            return
        
        self._is_running = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        print("Receiver listener stopped.")

    def get_history(self):
        """Thread-safe method returning a snapshot list of all recorded notes."""
        with self._lock:
            return list(self._history)

    def clear_history(self):
        """Thread-safe method to reset the history log."""
        with self._lock:
            self._history.clear()


# --- Example Usage ---
if __name__ == "__main__":
    receiver = M_Receiver(max_history=100)
    receiver.start()

    print("Listening... Play a melody or sing. Press Ctrl+C to view history and exit.")
    try:
        while True:
            # Other objects/threads can poll the history whenever they want
            history = receiver.get_history()
            if history:
                latest = history[-1]
                print(f"Total Logged: {len(history)} | Latest -> Note: {latest['note']:<4} ({latest['frequency']:.1f} Hz)", end="\r", flush=True)
            time.sleep(0.2)
            
    except KeyboardInterrupt:
        receiver.stop()
        print("\n\nFinal Recorded Note History:")
        for item in receiver.get_history():
            print(f"Note: {item['note']}, Freq: {item['frequency']:.2f} Hz, Time: {item['timestamp']:.2f}")