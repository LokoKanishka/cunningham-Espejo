import os
import sys
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import openclaw_direct_chat as direct_chat  # noqa: E402


READER_STRESS_50 = [
    "Bueno luci abri el libro 1 que quiero que empieces a leer desde el capitulo 1.",
    "Che, por favor abrime el libro 1 asi arrancamos lectura.",
    "Cuando puedas, leer libro 1 y seguimos desde ahi.",
    "Dale, abri libro 1 porque quiero escuchar el comienzo.",
    "Luci, leeme libro 1 tranqui y despues vemos.",
    "Antes de seguir, abri el libro numero 1.",
    "Quiero que ahora mismo abri el libro 1 y empieces.",
    "Mira, para esta prueba: abrime libro 1 por favor.",
    "Necesito foco, abri el libro 1 y no te vayas por las ramas.",
    "En serio, leer libro 1 que estamos validando reader.",
    "Para testear, decime biblioteca primero y listo.",
    "Che luci, mostrame la biblioteca asi elijo bien.",
    "Podrias abrir la biblioteca y listar mis libros?",
    "Antes de nada, biblioteca rescan por favor.",
    "Necesito que actualices biblioteca porque agregue archivos.",
    "Pasame estado lectura asi veo donde quedamos.",
    "Bueno, decime donde voy en la lectura actual.",
    "Quiero status lectura completo con cursor y todo.",
    "Si estas leyendo, por favor pausa lectura un segundo.",
    "Detenete un toque que te quiero preguntar algo.",
    "Te pido pausar lectura porque anote mal.",
    "Necesito que pares la lectura ahora, gracias.",
    "Stop lectura por favor, se mezclo el audio.",
    "Listo, continuar cuando puedas.",
    "Dale segui leyendo desde donde estabas.",
    "Che, siguiente bloque porfa.",
    "Quiero que sigas leyendo ahora mismo.",
    "Next, seguimos con el proximo bloque.",
    "Podrias continuar desde \"matriz\" para retomar exacto?",
    "Intenta continuar desde \"capitulo uno\" por favor.",
    "Ok continua la lectura desde \"matriz\" que me perdi.",
    "Ok contiuna la lectura desde \"matriz\" por favor.",
    "Ok contionua la lectura desde \"matriz\" y retoma ya.",
    "Necesito volver una frase porque no entendi.",
    "Podrias volver un parrafo asi lo repaso?",
    "Che, repetir ese bloque porque se corto.",
    "Repeti lo ultimo, no llegue a escucharlo.",
    "Poneme modo manual on para avanzar paso a paso.",
    "Dejemos manual on por ahora asi controlo yo.",
    "Cambiame modo manual off y que siga solo.",
    "Quiero manual off para volver al autopiloto.",
    "Activame continuo on asi no tengo que pedir siguiente.",
    "Mejor continuo off porque quiero ir de a poco.",
    "Luci, por favor abri libro 2 y despues seguir leyendo.",
    "Si podes, abrime el libro numero 3 para arrancar.",
    "Che, leer libro 4 que ese es el correcto.",
    "Te digo una larga: bueno luci, cuando termines eso abri el libro 5 y empeza a leer.",
    "Mira esta frase larga: necesito que abri el libro 6 porque quiero escuchar el inicio ahora.",
    "Para validar NLU: podrias, sin vueltas, abrime libro 7 y arrancar lectura continua?",
    "Otra mas: loco abri el libro 8 asi hacemos la prueba de punta a punta.",
    "En esta tambien: bueno, si no es molestia, leer libro 9 y luego estado lectura.",
    "Con ruido verbal: eh luci mm abri el libro 10 dale.",
    "Comando embebido final: che, antes de cerrar, abri el libro 11 que mañana sigo.",
]


class TestReaderCommandStress(unittest.TestCase):
    def test_extract_reader_book_index_embedded_sentence(self) -> None:
        msg = "bueno luci abri el libro 1 que quiero que empieces a leer desde el capitulo 1"
        self.assertEqual(direct_chat._extract_reader_book_index(msg), 1)

    def test_reader_control_detection_stress_50_embedded(self) -> None:
        missing: list[str] = []
        for phrase in READER_STRESS_50:
            if not direct_chat._is_reader_control_command(phrase):
                missing.append(phrase)
        self.assertEqual(missing, [], f"Frases no detectadas ({len(missing)}): {missing}")


if __name__ == "__main__":
    unittest.main()
