"""Standalone local STT worker - runs in a subprocess with no Qt.

Usage:
    python scripts/whisper_stt_worker.py \
        --transcript game_qa_mic.txt \
        --language zh \
        --backend whisper \
        --model base \
        --silence-ms 1000

Captures mic audio, detects speech segments, transcribes with a local backend,
appends results to --transcript file (one line per utterance).
"""
import argparse
import io
import os
import sys
import tempfile
import time
import wave


def _debug() -> bool:
    return os.environ.get("LOL_COACH_DEBUG_STT", "").strip().lower() in {"1", "true"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--language", default="zh")
    parser.add_argument("--backend", default="whisper", choices=["whisper", "funasr"])
    parser.add_argument("--model", default="base")
    parser.add_argument("--silence-ms", type=int, default=1000)
    parser.add_argument("--pause-flag", default="")
    args = parser.parse_args()

    sample_rate = 16000
    chunk_frames = 1024
    silence_threshold = 0.01
    min_speech_seconds = 0.4
    silence_frames = max(1, int(args.silence_ms / 1000 * sample_rate / chunk_frames))

    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        print(f"[local_stt_worker] missing dependency: {exc}", file=sys.stderr)
        sys.exit(1)

    if _debug():
        print(
            f"[local_stt_worker] loading backend={args.backend} model={args.model} language={args.language}",
            file=sys.stderr,
            flush=True,
        )

    try:
        if args.backend == "funasr":
            from funasr import AutoModel

            model = AutoModel(
                model=args.model,
                vad_model="fsmn-vad",
                punc_model="ct-punc",
                device="cpu",
                disable_update=True,
            )
        else:
            from faster_whisper import WhisperModel

            model = WhisperModel(
                args.model,
                device="cpu",
                compute_type="int8",
                cpu_threads=4,
                local_files_only=False,
            )
    except ImportError as exc:
        print(f"[local_stt_worker] missing backend dependency: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    except Exception as exc:
        print(f"[local_stt_worker] model init failed: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)

    if _debug():
        print(f"[local_stt_worker] ready, writing to {args.transcript}", file=sys.stderr, flush=True)

    transcript_path = args.transcript
    os.makedirs(os.path.dirname(os.path.abspath(transcript_path)), exist_ok=True)
    if not os.path.exists(transcript_path):
        open(transcript_path, "w", encoding="utf-8").close()

    buffer: list[bytes] = []
    silent_chunks = 0
    speaking = False

    def callback(indata, frames, time_info, status):
        nonlocal silent_chunks, speaking
        pcm = (indata[:, 0] * 32767).astype("int16").tobytes()
        rms = float(np.sqrt(np.mean(indata ** 2)))
        buffer.append(pcm)
        if rms >= silence_threshold:
            speaking = True
            silent_chunks = 0
        elif speaking:
            silent_chunks += 1

    try:
        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=chunk_frames,
            callback=callback,
        ):
            while True:
                time.sleep(0.1)
                if speaking and silent_chunks >= silence_frames:
                    pcm_data = b"".join(buffer)
                    buffer.clear()
                    speaking = False
                    silent_chunks = 0
                    if args.pause_flag and os.path.exists(args.pause_flag):
                        if _debug():
                            print(
                                "[local_stt_worker] paused, discarding captured clip during TTS",
                                file=sys.stderr,
                                flush=True,
                            )
                        continue
                    duration = len(pcm_data) / (sample_rate * 2)
                    if duration < min_speech_seconds:
                        if _debug():
                            print(
                                f"[local_stt_worker] clip too short {duration:.2f}s, skip",
                                file=sys.stderr,
                                flush=True,
                            )
                        continue
                    print(
                        f"[local_stt_worker] transcribing backend={args.backend} {duration:.1f}s clip",
                        file=sys.stderr,
                        flush=True,
                    )
                    started = time.time()
                    text = _transcribe(model, pcm_data, args.language, sample_rate, backend=args.backend)
                    elapsed = time.time() - started
                    print(
                        f"[local_stt_worker] transcribe_ms={elapsed*1000:.0f} result={text!r}",
                        file=sys.stderr,
                        flush=True,
                    )
                    if text:
                        with open(transcript_path, "a", encoding="utf-8") as handle:
                            handle.write(text + "\n")
    except KeyboardInterrupt:
        pass


def _transcribe(model, pcm_bytes: bytes, language: str, sample_rate: int, *, backend: str) -> str:
    import numpy as np

    if backend == "funasr":
        # Pass waveform samples directly so FunASR does not depend on
        # torchaudio/torchcodec/ffmpeg to reopen the temp file.
        speech = np.frombuffer(pcm_bytes, dtype=np.int16).astype("float32") / 32768.0
        result = model.generate(input=speech, batch_size_s=0)
        if isinstance(result, list) and result:
            return str(result[0].get("text", "")).strip()
        return ""

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    wav_bytes = buf.getvalue()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        handle.write(wav_bytes)
        tmp = handle.name
    try:
        segments, _ = model.transcribe(tmp, language=language, beam_size=5, vad_filter=True)
        return "".join(segment.text for segment in segments).strip()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


if __name__ == "__main__":
    main()
