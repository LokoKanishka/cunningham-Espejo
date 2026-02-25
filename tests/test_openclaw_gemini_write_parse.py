import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))


import openclaw_direct_chat as direct_chat  # noqa: E402


class TestGeminiWriteParser(unittest.TestCase):
    def test_extract_with_quotes(self) -> None:
        msg = 'cunn: en gemini escribí "Hola gemini" y da enter'
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertEqual(out, "Hola gemini")

    def test_extract_last_write_verb(self) -> None:
        msg = "decile a cunn que abra gemini y escriba hola gemini"
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertEqual(out, "hola gemini")

    def test_extract_none_without_gemini(self) -> None:
        msg = "escribi hola mundo y da enter"
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertIsNone(out)

    def test_extract_escribile_chat_phrase(self) -> None:
        msg = "ahora en el chat escribile hola gemini"
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertEqual(out, "hola gemini")

    def test_extract_with_redacta(self) -> None:
        msg = "cunn en gemini redacta Hola gemini"
        out = direct_chat._extract_gemini_write_request(msg)
        self.assertEqual(out, "hola gemini")

    def test_extract_gemini_ask_direct(self) -> None:
        msg = "podrias preguntarle a gemini que es un proton"
        out = direct_chat._extract_gemini_ask_request(msg)
        self.assertEqual(out, "es un proton")

    def test_extract_gemini_ask_after_open(self) -> None:
        msg = "hola, abri gemini y preguntale la receta de los biñuelitos de manzana"
        out = direct_chat._extract_gemini_ask_request(msg)
        self.assertEqual(out, "la receta de los binuelitos de manzana")

    def test_extract_gemini_ask_busca(self) -> None:
        msg = "cunn busca en gemini que es la fotosintesis"
        out = direct_chat._extract_gemini_ask_request(msg)
        self.assertEqual(out, "es la fotosintesis")

    def test_extract_gemini_ask_busca_topic_before_site(self) -> None:
        msg = "cunn busca sobre protones en gemini"
        out = direct_chat._extract_gemini_ask_request(msg)
        self.assertEqual(out, "protones")

    def test_extract_gemini_ask_que_busque_topic_before_site(self) -> None:
        msg = "que busque relatividad en gemini"
        out = direct_chat._extract_gemini_ask_request(msg)
        self.assertEqual(out, "relatividad")


if __name__ == "__main__":
    unittest.main()
