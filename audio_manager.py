import pygame
import os

class AudioManager:
    def __init__(self):
        pygame.mixer.init()
        self.audio_files = {}  # Dictionary to store audio files by their relative path
        self.current_sound = None

    def load_audio(self, file_path):
        """Load a single audio file and store it in the dictionary"""
        sound = pygame.mixer.Sound(file_path)
        self.audio_files[file_path] = sound
        return sound
    
    def get_audio_length(self, file_path=None):
        """Get the length of an audio file in seconds"""
        if file_path:
            if file_path in self.audio_files:
                return self.audio_files[file_path].get_length()
            else:
                raise FileNotFoundError(f"Audio file '{file_path}' not loaded")
        elif self.current_sound:
            return self.current_sound.get_length()
        else:
            return 0


    def load_multiple_audios(self, file_paths):
        """Load multiple audio files at once"""
        for file_path in file_paths:
            self.load_audio(file_path)

    def play_audio(self, file_path=None):
        """Play audio by file path (ID) or play the current sound if no path specified"""
        if file_path:
            if file_path in self.audio_files:
                self.current_sound = self.audio_files[file_path]
                self.current_sound.play()
            else:
                raise FileNotFoundError(f"Audio file '{file_path}' not loaded")
        elif self.current_sound:
            self.current_sound.play()

    def is_playing(self):
        if self.current_sound:
            return pygame.mixer.get_busy()
        return False
    
    

    def get_loaded_files(self):
        """Return a list of all loaded audio file paths"""
        return list(self.audio_files.keys())

    def unload_audio(self, file_path, remove=True):
        """Remove an audio file from memory"""
        if file_path in self.audio_files:
            del self.audio_files[file_path]
            if self.current_sound == self.audio_files.get(file_path):
                self.current_sound = None
            if remove:
                os.remove(file_path)