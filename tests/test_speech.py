import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from hackerterminal.speech import transcribe


class SpeechTests(unittest.TestCase):
    def test_model_and_decode_options(self):
        model = Mock()
        model.transcribe.return_value = (iter([SimpleNamespace(text=' Olá '), SimpleNamespace(text=''), SimpleNamespace(text='mundo')]), None)
        factory = Mock(return_value=model)
        self.assertEqual(transcribe('audio.wav', factory), 'Olá mundo')
        factory.assert_called_once_with('large-v3', device='cpu', compute_type='int8')
        model.transcribe.assert_called_once_with('audio.wav', beam_size=5, vad_filter=True, condition_on_previous_text=False, task='transcribe')

    def test_silence(self):
        model = Mock()
        model.transcribe.return_value = (iter([]), None)
        self.assertEqual(transcribe('silence.wav', Mock(return_value=model)), '')

    def test_decode_failure_propagates(self):
        model = Mock()
        model.transcribe.side_effect = ValueError('invalid audio')
        with self.assertRaises(ValueError):
            transcribe('bad.wav', Mock(return_value=model))
