"""Varias fotos en un mismo mensaje.

En leche, el bulto nuevo guarda todas las de ese mensaje y igual pide
el empaque vacío aparte: ninguna de esas fotos queda como vacío.

En el empaque vacío de leche, suero y azúcar también se guardan todas.
Los demás productos, y el bulto nuevo de suero y azúcar, siguen con
una sola foto: la primera del mensaje.
"""
import asyncio
import os
import unittest

os.environ["PESADAS_NO_ARRANCAR"] = "1"
os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("XAI_API_KEY", "test-key")

import main


def _paso_transferencia() -> int:
    return next(i for i, p in enumerate(main.PREGUNTAS) if p["tipo"] == "transferencia")


class Canal:
    def __init__(self, cid=42):
        self.id = cid
        self.messages = []

    async def send(self, content):
        self.messages.append(content)


class Autor:
    def __init__(self, user_id=7):
        self.id = user_id


class Adjunto:
    def __init__(self, filename, content_type="image/jpeg"):
        self.filename = filename
        self.url = f"https://cdn.example/{filename}"
        self.content_type = content_type


class Mensaje:
    def __init__(self, content, canal, attachments=None):
        self.content = content
        self.channel = canal
        self.attachments = list(attachments or [])
        self.author = Autor()
        self.reactions = []

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)


class TestFotosTransferenciaUnaPorMensaje(unittest.TestCase):
    def setUp(self):
        main.conversation_state.clear()

    def tearDown(self):
        main.conversation_state.clear()

    def _estado(self, canal):
        state = main._crear_estado(7)
        state["paso"] = _paso_transferencia()
        main.conversation_state[str(canal.id)] = state
        return state

    def test_dos_fotos_en_bulto_nuevo_piden_el_vacio(self):
        for producto in ("Leche", "leche", "LECHE"):
            with self.subTest(producto=producto):
                asyncio.run(self._assert_dos_en_nuevo(producto))

    async def _assert_dos_en_nuevo(self, producto="Leche"):
        canal = Canal()
        state = self._estado(canal)
        paso = state["paso"]
        state["fotos_tx"] = {
            "productos": [producto],
            "idx": 0,
            "paso_foto": "nuevo",
            "capturas": {},
        }
        await main.manejar_respuesta(
            Mensaje(
                "",
                canal,
                [Adjunto("bulto-nuevo.jpg"), Adjunto("otra-llena.jpg")],
            )
        )

        slot = state["fotos_tx"]["capturas"][producto]
        self.assertEqual(
            [f["filename"] for f in slot["nuevo"]],
            ["bulto-nuevo.jpg", "otra-llena.jpg"],
        )
        self.assertEqual(
            [f["url"] for f in slot["nuevo"]],
            [
                "https://cdn.example/bulto-nuevo.jpg",
                "https://cdn.example/otra-llena.jpg",
            ],
        )
        for foto in slot["nuevo"]:
            self.assertEqual(set(foto), {"filename", "url", "content_type"})
        self.assertIsNone(slot["vacio"])
        self.assertEqual(list(state["fotos_tx"]["capturas"]), [producto])
        self.assertEqual(state["fotos_tx"]["paso_foto"], "vacio")
        self.assertEqual(state["fotos_tx"]["idx"], 0)
        self.assertEqual(state["paso"], paso)
        self.assertEqual(canal.messages, [main._texto_pedir_foto(producto, "vacio")])
        self.assertNotIn("Listo, ya tengo las fotos de la transferencia.", canal.messages)
        self.assertNotIn("fotos_transferencia", state["answers"])

    def test_varias_fotos_en_bulto_nuevo_tampoco_guardan_el_vacio(self):
        asyncio.run(self._assert_tres_en_nuevo())

    async def _assert_tres_en_nuevo(self):
        canal = Canal()
        state = self._estado(canal)
        state["fotos_tx"] = {
            "productos": ["Leche"],
            "idx": 0,
            "paso_foto": "nuevo",
            "capturas": {},
        }
        await main.manejar_respuesta(
            Mensaje(
                "",
                canal,
                [
                    Adjunto("bulto-nuevo.jpg"),
                    Adjunto("segunda.jpg"),
                    Adjunto("tercera.jpg"),
                ],
            )
        )

        slot = state["fotos_tx"]["capturas"]["Leche"]
        self.assertEqual(
            [f["filename"] for f in slot["nuevo"]],
            ["bulto-nuevo.jpg", "segunda.jpg", "tercera.jpg"],
        )
        self.assertIsNone(slot["vacio"])
        self.assertEqual(canal.messages, [main._texto_pedir_foto("Leche", "vacio")])
        self.assertIsNotNone(state["fotos_tx"])

    def test_fotos_extra_en_empaque_vacio_no_avanzan_al_siguiente(self):
        asyncio.run(self._assert_dos_en_vacio())

    async def _assert_dos_en_vacio(self):
        canal = Canal()
        state = self._estado(canal)
        state["fotos_tx"] = {
            "productos": ["Leche", "Azúcar"],
            "idx": 0,
            "paso_foto": "vacio",
            "capturas": {
                "Leche": {
                    "nuevo": {
                        "filename": "bulto-nuevo.jpg",
                        "url": "https://cdn.example/bulto-nuevo.jpg",
                        "content_type": "image/jpeg",
                    },
                    "vacio": None,
                }
            },
        }
        await main.manejar_respuesta(
            Mensaje(
                "",
                canal,
                [Adjunto("empaque-vacio.jpg"), Adjunto("otro-empaque.jpg")],
            )
        )

        leche = state["fotos_tx"]["capturas"]["Leche"]
        self.assertEqual(leche["nuevo"]["filename"], "bulto-nuevo.jpg")
        self.assertEqual(
            [f["filename"] for f in leche["vacio"]],
            ["empaque-vacio.jpg", "otro-empaque.jpg"],
        )
        self.assertNotIn("Azúcar", state["fotos_tx"]["capturas"])
        self.assertEqual(state["fotos_tx"]["idx"], 1)
        self.assertEqual(state["fotos_tx"]["paso_foto"], "nuevo")
        self.assertEqual(
            canal.messages,
            [main._texto_pedir_foto("Azúcar", "nuevo")],
        )
        self.assertNotIn("Listo, ya tengo las fotos de la transferencia.", canal.messages)
        self.assertNotIn("fotos_transferencia", state["answers"])

    def test_vacio_de_leche_suero_y_azucar_guarda_las_dos_fotos(self):
        for producto in ("Leche", "Suero", "SUERO", "Azúcar", "azucar", "AZÚCAR"):
            with self.subTest(producto=producto):
                asyncio.run(self._assert_vacio_dos_en_reporte(producto))

    async def _assert_vacio_dos_en_reporte(self, producto):
        canal = Canal()
        state = self._estado(canal)
        state["fotos_tx"] = {
            "productos": [producto],
            "idx": 0,
            "paso_foto": "vacio",
            "capturas": {
                producto: {
                    "nuevo": {
                        "filename": "bulto.jpg",
                        "url": "https://cdn.example/bulto.jpg",
                        "content_type": "image/jpeg",
                    },
                    "vacio": None,
                }
            },
        }
        await main.manejar_respuesta(
            Mensaje("", canal, [Adjunto("vacio-1.jpg"), Adjunto("vacio-2.jpg")])
        )

        guardadas = state["answers"]["fotos_transferencia"][producto]
        self.assertEqual(guardadas["nuevo"]["filename"], "bulto.jpg")
        self.assertEqual(
            [f["filename"] for f in guardadas["vacio"]],
            ["vacio-1.jpg", "vacio-2.jpg"],
        )
        self.assertEqual(
            [f["url"] for f in guardadas["vacio"]],
            [
                "https://cdn.example/vacio-1.jpg",
                "https://cdn.example/vacio-2.jpg",
            ],
        )
        self.assertIsNone(state["fotos_tx"])
        self.assertIn("Listo, ya tengo las fotos de la transferencia.", canal.messages)

    def test_suero_y_azucar_en_bulto_nuevo_siguen_con_una_foto(self):
        for producto in ("Suero", "Azúcar", "azucar", "AZÚCAR"):
            with self.subTest(producto=producto):
                asyncio.run(self._assert_nuevo_una(producto))

    async def _assert_nuevo_una(self, producto):
        canal = Canal()
        state = self._estado(canal)
        state["fotos_tx"] = {
            "productos": [producto],
            "idx": 0,
            "paso_foto": "nuevo",
            "capturas": {},
        }
        await main.manejar_respuesta(
            Mensaje("", canal, [Adjunto("nuevo-1.jpg"), Adjunto("nuevo-2.jpg")])
        )

        slot = state["fotos_tx"]["capturas"][producto]
        self.assertEqual(slot["nuevo"]["filename"], "nuevo-1.jpg")
        self.assertEqual(slot["nuevo"]["url"], "https://cdn.example/nuevo-1.jpg")
        self.assertNotIn("nuevo-2.jpg", slot["nuevo"]["filename"])
        self.assertNotIn("nuevo-2.jpg", slot["nuevo"]["url"])
        self.assertIsNone(slot["vacio"])
        self.assertEqual(state["fotos_tx"]["paso_foto"], "vacio")
        self.assertEqual(state["fotos_tx"]["idx"], 0)
        self.assertEqual(canal.messages, [main._texto_pedir_foto(producto, "vacio")])
        self.assertNotIn("fotos_transferencia", state["answers"])

    def test_otro_producto_sigue_con_una_foto_por_paso(self):
        for producto in ("Estabilizante", "Crema de Leche", "Glucosa", "Arequipe"):
            with self.subTest(producto=producto):
                asyncio.run(self._assert_una_foto(producto))

    async def _assert_una_foto(self, producto):
        canal = Canal()
        state = self._estado(canal)
        state["fotos_tx"] = {
            "productos": [producto, "Azúcar"],
            "idx": 0,
            "paso_foto": "nuevo",
            "capturas": {},
        }
        await main.manejar_respuesta(
            Mensaje("", canal, [Adjunto("nuevo-1.jpg"), Adjunto("nuevo-2.jpg")])
        )

        slot = state["fotos_tx"]["capturas"][producto]
        self.assertEqual(
            slot["nuevo"],
            {
                "filename": "nuevo-1.jpg",
                "url": "https://cdn.example/nuevo-1.jpg",
                "content_type": "image/jpeg",
            },
        )
        self.assertIsNone(slot["vacio"])
        self.assertEqual(state["fotos_tx"]["paso_foto"], "vacio")
        self.assertEqual(state["fotos_tx"]["idx"], 0)
        self.assertEqual(canal.messages, [main._texto_pedir_foto(producto, "vacio")])

        await main.manejar_respuesta(
            Mensaje("", canal, [Adjunto("vacio-1.jpg"), Adjunto("vacio-2.jpg")])
        )
        self.assertEqual(
            slot["vacio"],
            {
                "filename": "vacio-1.jpg",
                "url": "https://cdn.example/vacio-1.jpg",
                "content_type": "image/jpeg",
            },
        )
        self.assertNotIn("Azúcar", state["fotos_tx"]["capturas"])
        self.assertEqual(state["fotos_tx"]["idx"], 1)
        self.assertEqual(state["fotos_tx"]["paso_foto"], "nuevo")
        self.assertEqual(canal.messages[-1], main._texto_pedir_foto("Azúcar", "nuevo"))
        self.assertNotIn("fotos_transferencia", state["answers"])


if __name__ == "__main__":
    unittest.main()
