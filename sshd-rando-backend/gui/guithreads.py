# Stub file for nogui mode - no PySide6 dependencies

class ThreadCancelled(Exception):
    """Exception raised when a thread is cancelled"""
    def __str__(self):
        return "Some thread was cancelled."

class RandomizationThread:
    """Stub for randomization thread"""
    cancelled = False
    callback = None
    
    def __init__(self):
        pass
    
    def run(self):
        """Run randomization in nogui mode"""
        try:
            from randomizer.randomize import randomize
            RandomizationThread.callback = self
            randomize()
        except Exception as e:
            import traceback
            print(f"Error: {e}")
            print(traceback.format_exc())
            return
        RandomizationThread.callback = None

class VerificationThread:
    """Stub for verification thread"""
    cancelled = False
    callback = None
    
    def __init__(self, verify_all: bool = False):
        self.verify_all = verify_all
    
    def set_verify_all(self, should_verify_all: bool):
        self.verify_all = should_verify_all
    
    def run(self):
        """Run verification in nogui mode"""
        try:
            from randomizer.verify_extract import verify_extract
            VerificationThread.callback = self
            verify_extract(verify_all_files=self.verify_all)
        except Exception as e:
            import traceback
            print(f"Error: {e}")
            print(traceback.format_exc())
        VerificationThread.callback = None

