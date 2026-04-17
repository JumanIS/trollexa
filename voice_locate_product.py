import sys
import wave
import tempfile
from pathlib import Path
import whisper
import sounddevice as sd
from locate_product import ProductSearchEngine

"""
This script integrates OpenAI Whisper (STT) and the Product Search Engine.
It allows the user to speak a product name, transcribes it to text,
and then finds the product's location in the store.
"""

class VoiceProductLocator:
    def __init__(self, model_name="base"):
        # Load the Whisper model once (this takes some time and memory)
        print(f"--- Loading Whisper Model ({model_name}) ---")
        self.model = whisper.load_model(model_name)
        # Initialize the search engine to match products
        self.search_engine = ProductSearchEngine()

    def transcribe(self, audio_path: str):
        """ Converts an audio file (.wav) into text string """
        print(f"Transcribing audio: {audio_path}")
        result = self.model.transcribe(audio_path, fp16=False, language='en')
        return result.get("text", "").strip()

    def voice_to_product(self, audio_path: str):
        """ 
        The main pipeline: 
        1. Transcribe audio 
        2. Search for product 
        3. Return matches
        """
        text = self.transcribe(audio_path)
        if not text:
            print("No speech detected.")
            return []
            
        print(f"Recognized Text: '{text}'")
        matches = self.search_engine.search(text)
        return matches

def record_audio(output_path, seconds=4):
    """ Simple helper to record voice from the microphone """
    fs = 16000 # Sample rate
    print(f"Recording for {seconds} seconds... Speak now!")
    recording = sd.rec(int(seconds * fs), samplerate=fs, channels=1, dtype='int16')
    sd.wait() # Wait until recording is finished
    
    # Save as WAV file
    with wave.open(output_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(fs)
        wf.writeframes(recording.tobytes())
    return output_path

# CLI mode for testing
if __name__ == "__main__":
    locator = VoiceProductLocator(model_name="base")
    
    while True:
        cmd = input("\nPress Enter to search by voice (or type 'exit'): ").strip().lower()
        if cmd == 'exit': break
        
        # Create a temporary file for the recording
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            
        try:
            record_audio(tmp_path)
            results = locator.voice_to_product(tmp_path)
            
            if results:
                print("\n--- Search Results ---")
                for i, r in enumerate(results, 1):
                    print(f"{i}. {r['name']} at ({r['x_m']}, {r['y_m']}) [Confidence: {r['score']:.2f}]")
            else:
                print("No matching products found.")
        finally:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()
