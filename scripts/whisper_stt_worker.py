"""Standalone Whisper STT worker — runs in a subprocess with no Qt.

Usage:
    python scripts/whisper_stt_worker.py \
        --transcript game_qa_mic.txt \
        --language zh \
        --model base \
        --silence-ms 1000

Captures mic audio, detects speech segments, transcribes with Whisper,
appends results to --transcript file (one line per utterance).
"""
import argparse
import io
import os
import sys
import time
import wave
import tempfile

def _debug():
    return os.environ.get("LOL_COACH_DEBUG_STT", "").strip().lower() in {"1", "true"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--model", default="base")
    parser.add_argument("--silence-ms", type=int, default=1000)
    args = parser.parse_args()

    SAMPLE_RATE = 16000
    CHUNK_FRAMES = 1024
    SILENCE_THRESHOLD = 0.01
    MIN_SPEECH_SECONDS = 0.4
    silence_frames = max(1, int(args.silence_ms / 1000 * SAMPLE_RATE / CHUNK_FRAMES))

    try:
        import sounddevice as sd
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError as e:
        print(f"[whisper_worker] missing dependency: {e}", file=sys.stderr)
        sys.exit(1)

    if _debug():
        print(f"[whisper_worker] loading model={args.model} language={args.language}", file=sys.stderr, flush=True)

    model = WhisperModel(args.model, device="cpu", compute_type="int8",
                         cpu_threads=4, local_files_only=False)

    if _debug():
        print(f"[whisper_worker] ready, writing to {args.transcript}", file=sys.stderr, flush=True)

    transcript_path = args.transcript
    os.makedirs(os.path.dirname(os.path.abspath(transcript_path)), exist_ok=True)
    if not os.path.exists(transcript_path):
        open(transcript_path, "w", encoding="utf-8").close()

    buffer = []
    silent_chunks = 0
    speaking = False

    def callback(indata, frames, time_info, status):
        nonlocal silent_chunks, speaking
        pcm = (indata[:, 0] * 32767).astype("int16").tobytes()
        rms = float(np.sqrt(np.mean(indata ** 2)))
        buffer.append(pcm)
        if rms >= SILENCE_THRESHOLD:
            speaking = True
            silent_chunks = 0
        elif speaking:
            silent_chunks += 1

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                            dtype="float32", blocksize=CHUNK_FRAMES,
                            callback=callback):
            while True:
                time.sleep(0.1)
                if speaking and silent_chunks >= silence_frames:
                    pcm_data = b"".join(buffer)
                    buffer.clear()
                    speaking = False
                    silent_chunks = 0
                    duration = len(pcm_data) / (SAMPLE_RATE * 2)
                    if duration < MIN_SPEECH_SECONDS:
                        if _debug():
                            print(f"[whisper_worker] clip too short {duration:.2f}s, skip", file=sys.stderr, flush=True)
                        continue
                    print(f"[whisper_worker] transcribing {duration:.1f}s clip", file=sys.stderr, flush=True)
                    t_start = time.time()
                    text = _transcribe(model, pcm_data, args.language, SAMPLE_RATE)
                    t_elapsed = time.time() - t_start
                    print(f"[whisper_worker] transcribe_ms={t_elapsed*1000:.0f} result={text!r}", file=sys.stderr, flush=True)
                    if text:
                        with open(transcript_path, "a", encoding="utf-8") as f:
                            f.write(text + "\n")
    except KeyboardInterrupt:
        pass


def _transcribe(model, pcm_bytes: bytes, language: str, sample_rate: int) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    wav_bytes = buf.getvalue()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(wav_bytes)
        tmp = f.name
    try:
        segments, _ = model.transcribe(tmp, language=language, beam_size=5, vad_filter=True)
        return "".join(s.text for s in segments).strip()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


if __name__ == "__main__":
    main()
