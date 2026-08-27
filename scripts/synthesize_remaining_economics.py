import sys
import subprocess
import time
from pathlib import Path

def main():
    start_ch = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    end_ch = int(sys.argv[2]) if len(sys.argv) > 2 else 19
    
    print(f"=== Starting Batch Audio Synthesis for Economics Chapters {start_ch} to {end_ch} ===")
    
    for ch in range(start_ch, end_ch + 1):
        script_file = Path(f"output_lectures/fundamentals_of_economics/fundamentals_of_economics_chapter_{ch}_script.json")
        audio_file = Path(f"output_lectures/fundamentals_of_economics/fundamentals_of_economics_chapter_{ch}_lecture.mp3")
        
        if not script_file.exists():
            print(f"Error: Script file {script_file} does not exist!")
            sys.exit(1)
            
        print(f"\n[{ch}/{end_ch}] Synthesizing Chapter {ch} from {script_file}...")
        cmd = [
            ".venv/bin/python",
            "lecture_generator.py",
            "--book", "fundamentals_of_economics",
            "--chapter", str(ch),
            "--script-file", str(script_file),
            "--voice", "en-NG-AbeoNeural",
            "--rate=-18%"
        ]
        
        start_t = time.time()
        res = subprocess.run(cmd, capture_output=False)
        elapsed = time.time() - start_t
        
        if res.returncode != 0:
            print(f"FAILED on Chapter {ch} with exit code {res.returncode}")
            sys.exit(res.returncode)
            
        if audio_file.exists():
            size_mb = audio_file.stat().st_size / (1024 * 1024)
            print(f"[SUCCESS] Chapter {ch} synthesized in {elapsed:.1f}s ({size_mb:.2f} MB)")
        else:
            print(f"WARNING: Audio file {audio_file} not found after run!")
            
    print(f"\n=======================================================")
    print(f"ALL CHAPTERS {start_ch} TO {end_ch} SYNTHESIZED SUCCESSFULLY!")
    print(f"=======================================================")

if __name__ == "__main__":
    main()
