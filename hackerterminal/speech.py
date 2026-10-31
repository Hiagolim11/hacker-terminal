"""Optional, isolated local speech recognition worker (no GTK imports)."""
from __future__ import annotations

import argparse
import json


def transcribe(source, model_factory=None):
    if model_factory is None:
        from faster_whisper import WhisperModel
        model_factory = WhisperModel
    model = model_factory('large-v3', device='cpu', compute_type='int8')
    segments, _ = model.transcribe(source, beam_size=5, vad_filter=True,
                                  condition_on_previous_text=False, task='transcribe')
    return ' '.join(segment.text.strip() for segment in segments if segment.text.strip())


def record(seconds=10):
    import sounddevice as sd
    import numpy as np
    audio = sd.rec(int(seconds * 16000), samplerate=16000, channels=1, dtype='float32')
    sd.wait()
    audio = np.asarray(audio).reshape(-1)
    if not np.isfinite(audio).all():
        raise ValueError('O microfone retornou áudio inválido.')
    return audio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file')
    args = parser.parse_args()
    try:
        result = transcribe(args.file if args.file else record())
        print(json.dumps({'text': result}, ensure_ascii=False))
        return 0
    except ImportError:
        print(json.dumps({'error': 'Instale requirements-speech.txt no Python usado pelo aplicativo. Para microfone, instale também libportaudio2.'}))
    except Exception as error:
        print(json.dumps({'error': str(error)}))
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
