import requests
import json
import re
import sys
import time
import os
import copy
from dataclasses import dataclass

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ═══════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════
SIZE         = 7
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "phi3:latest"

PLAYER = "K"
CHEST  = "C"
OGRE   = "O"
DOOR   = "D"
KEY    = "L"
EMPTY  = "."

# ═══════════════════════════════════════════════════════════
#  ENTIDADES  (spec §4.2)
# ═══════════════════════════════════════════════════════════

class Jugador:
    def __init__(self, r, c):
        self.r           = r
        self.c           = c
        self.hp          = 3.0
        self.oro         = 0
        self.tiene_llave = False
        self.defendiendo = False

    @property
    def pos(self): return (self.r, self.c)
    @property
    def vivo(self): return self.hp > 0


class Orco:
    def __init__(self, r, c, idx=1, hp=2.0):
        self.r           = r
        self.c           = c
        self.hp          = float(hp)
        self.idx         = idx

    @property
    def pos(self): return (self.r, self.c)
    @property
    def vivo(self): return self.hp > 0


class Cofre:
    def __init__(self, r, c):
        self.r       = r
        self.c       = c
        self.abierto = False

    @property
    def pos(self): return (self.r, self.c)


class Puerta:
    def __init__(self, r, c):
        self.r = r
        self.c = c

    @property
    def pos(self): return (self.r, self.c)


class Llave:
    def __init__(self, r, c):
        self.r        = r
        self.c        = c
        self.recogida = False

    @property
    def pos(self): return (self.r, self.c)


# ═══════════════════════════════════════════════════════════
#  ACCIONES SIMBÓLICAS
# ═══════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Accion:
    """
    Representación explícita de una acción simbólica.
    El LLM produce JSON; la capa simbólica lo traduce a esta estructura.
    """
    tipo: str
    direccion: str | None = None
    cantidad: int | None = None
    objetivo: str | None = None

    def a_dict(self) -> dict:
        data = {"tipo": self.tipo}
        if self.direccion is not None:
            data["direccion"] = self.direccion
        if self.cantidad is not None:
            data["cantidad"] = self.cantidad
        if self.objetivo is not None:
            data["objetivo"] = self.objetivo
        return data


def crear_accion(tipo: str, direccion: str | None = None,
                 cantidad: int | None = None, objetivo: str | None = None) -> Accion:
    return Accion(tipo=tipo, direccion=direccion, cantidad=cantidad, objetivo=objetivo)


# ═══════════════════════════════════════════════════════════
#  ESTADO DEL JUEGO  (spec §4.1)
# ═══════════════════════════════════════════════════════════

class Estado:
    """
    Única fuente de verdad del juego.
    Tablero 2D + todas las entidades.
    """
    def __init__(self):
        self.board        = [[EMPTY] * SIZE for _ in range(SIZE)]
        self.under_player = EMPTY

        self.jugador = None
        self.orcos   = []
        self.cofres  = []
        self.puerta  = None
        self.llave   = None

        self.nivel_terminado = False
        self.victoria        = False

        self._cargar_nivel_fijo()

    # ── nivel fijo ────────────────────────────────────────
    def _cargar_nivel_fijo(self):
        self.jugador = Jugador(3, 3)
        self.puerta  = Puerta(0, 3)
        self.llave   = Llave(5, 1)
        self.orcos   = [Orco(2, 5, idx=1, hp=2.0), Orco(5, 5, idx=2, hp=1.0)]
        self.cofres  = [Cofre(3, 1)]

        self.board[self.jugador.r][self.jugador.c] = PLAYER
        self.board[self.puerta.r][self.puerta.c] = DOOR
        self.board[self.llave.r][self.llave.c] = KEY
        for orco in self.orcos:
            self.board[orco.r][orco.c] = OGRE
        for cofre in self.cofres:
            self.board[cofre.r][cofre.c] = CHEST

    # ── acceso al tablero ─────────────────────────────────
    def _set(self, pos, symbol):
        r, c = pos
        self.board[r][c] = symbol

    def _get(self, pos):
        r, c = pos
        return self.board[r][c]

    def _dentro(self, r, c):
        return 0 <= r < SIZE and 0 <= c < SIZE

    # ── búsqueda de entidades ─────────────────────────────
    def orco_en(self, r, c):
        return next((o for o in self.orcos if o.pos == (r, c) and o.vivo), None)

    def cofre_en(self, r, c):
        return next((cf for cf in self.cofres if cf.pos == (r, c) and not cf.abierto), None)

    def find_nearest(self, symbol):
        jr, jc = self.jugador.pos
        best_dist, best_pos = float("inf"), None
        for r in range(SIZE):
            for c in range(SIZE):
                if self.board[r][c] == symbol:
                    dist = max(abs(jr - r), abs(jc - c))
                    if dist < best_dist:
                        best_dist, best_pos = dist, (r, c)
        return best_pos, best_dist

    # ── HUD ───────────────────────────────────────────────
    def print_board(self):
        j = self.jugador
        orcos_vivos = [o for o in self.orcos if o.vivo]

        print("\n" + "─" * 44)
        bj = _barra(j.hp, 3.0, 10)
        llave_str = "🗝 Llave" if j.tiene_llave else "sin llave"
        print(f"  HP: {bj} {j.hp:.1f}/3.0   Oro: {j.oro}   {llave_str}")
        for o in orcos_vivos:
            bo  = _barra(o.hp, 2.0, 10)
            print(f"  Orco {o.idx}: {bo} {o.hp:.1f}  pos({o.r},{o.c})")
        print("─" * 44)

        print("      " + "  ".join(str(c) for c in range(SIZE)))
        sep = "    +" + "---" * SIZE + "--+"
        print(sep)
        for r, row in enumerate(self.board):
            print(f"  {r} | " + "  ".join(row) + "  |")
        print(sep)
        print(f"  K=Caballero  O=Orco  C=Cofre  D=Puerta  L=Llave  .=Vacío")
        print(f"  Caballero → fila {j.r}, col {j.c}\n")


# ═══════════════════════════════════════════════════════════
#  VALIDACIÓN SIMBÓLICA  (spec §4.4)
#  Funciones puras: no modifican el estado.
# ═══════════════════════════════════════════════════════════

DIRS_8 = {            # spec §4.3 — 8 direcciones numeradas
    "arriba":             (-1,  0),
    "abajo":              ( 1,  0),
    "izquierda":          ( 0, -1),
    "derecha":            ( 0,  1),
    "arriba-izquierda":   (-1, -1),
    "arriba-derecha":     (-1,  1),
    "abajo-izquierda":    ( 1, -1),
    "abajo-derecha":      ( 1,  1),
}

DIRS_4 = {"arriba", "abajo", "izquierda", "derecha"}   # para abrir


def _celda_destino(entidad, direccion):
    """Devuelve (nr, nc) tras aplicar la dirección desde la posición de la entidad."""
    dr, dc = DIRS_8[direccion]
    return entidad.r + dr, entidad.c + dc


def _normalizar_accion(accion) -> dict:
    if isinstance(accion, Accion):
        return accion.a_dict()
    if isinstance(accion, dict):
        return dict(accion)
    raise TypeError(f"Acción no soportada: {type(accion)!r}")


def _resolver_entidad_en_copia(estado_copia: Estado, entidad_original):
    if isinstance(entidad_original, Jugador):
        return estado_copia.jugador
    if isinstance(entidad_original, Orco):
        return next((o for o in estado_copia.orcos if o.idx == entidad_original.idx), None)
    return None


def _copiar_estado(origen: Estado, destino: Estado):
    destino.board = copy.deepcopy(origen.board)
    destino.under_player = origen.under_player
    destino.jugador = copy.deepcopy(origen.jugador)
    destino.orcos = copy.deepcopy(origen.orcos)
    destino.cofres = copy.deepcopy(origen.cofres)
    destino.puerta = copy.deepcopy(origen.puerta)
    destino.llave = copy.deepcopy(origen.llave)
    destino.nivel_terminado = origen.nivel_terminado
    destino.victoria = origen.victoria


def validar(estado: Estado, entidad, accion) -> dict:
    """
    Decide si una acción es legal en el estado actual.
    NO modifica nada.
    Devuelve un dict rico para trazabilidad y debug.
    """
    a = _normalizar_accion(accion)
    tipo = a.get("tipo")

    info = {"valida": False, "motivo": "accion_desconocida", "tipo": tipo}

    if tipo == "esperar":
        info.update(valida=True, motivo="ok")
        return info

    if tipo == "mover":
        d = a.get("direccion")
        if d not in DIRS_8:
            info["motivo"] = "direccion_invalida"
            return info
        nr, nc = _celda_destino(entidad, d)
        if not estado._dentro(nr, nc):
            info["motivo"] = "fuera_de_tablero"
            return info
        sym = estado._get((nr, nc))
        if isinstance(entidad, Jugador):
            if sym in (EMPTY, DOOR, KEY):
                info.update(valida=True, motivo="ok", nueva_pos=(nr, nc), celda_destino=sym)
            else:
                info.update(motivo="celda_ocupada", nueva_pos=(nr, nc), celda_destino=sym)
        else:
            if sym == EMPTY:
                info.update(valida=True, motivo="ok", nueva_pos=(nr, nc), celda_destino=sym)
            else:
                info.update(motivo="celda_ocupada", nueva_pos=(nr, nc), celda_destino=sym)
        return info

    if tipo == "atacar":
        d = a.get("direccion")
        if d not in DIRS_8:
            info["motivo"] = "direccion_invalida"
            return info
        nr, nc = _celda_destino(entidad, d)
        if not estado._dentro(nr, nc):
            info["motivo"] = "fuera_de_tablero"
            return info
        sym = estado._get((nr, nc))
        objetivo_valido = OGRE if isinstance(entidad, Jugador) else PLAYER
        if sym == objetivo_valido:
            info.update(valida=True, motivo="ok", objetivo_pos=(nr, nc), celda_destino=sym)
        else:
            info.update(motivo="sin_objetivo_valido", objetivo_pos=(nr, nc), celda_destino=sym)
        return info

    if tipo == "abrir":
        d = a.get("direccion")
        if d not in DIRS_4:
            info["motivo"] = "direccion_invalida"
            return info
        nr, nc = _celda_destino(entidad, d)
        if not estado._dentro(nr, nc):
            info["motivo"] = "fuera_de_tablero"
            return info
        sym = estado._get((nr, nc))
        if sym == CHEST:
            info.update(valida=True, motivo="ok", objetivo_pos=(nr, nc), celda_destino=sym)
        else:
            info.update(motivo="no_hay_cofre", objetivo_pos=(nr, nc), celda_destino=sym)
        return info

    if tipo == "defensa":
        if isinstance(entidad, Jugador):
            info.update(valida=True, motivo="ok")
        else:
            info["motivo"] = "solo_jugador"
        return info

    return info


def _aplicar_accion_en_estado(estado: Estado, entidad, accion, *, silencioso: bool = False) -> bool:
    """
    Aplica efectos sobre EL estado recibido, asumiendo que la acción ya fue validada.
    Sirve tanto para simular (probar) como para ejecutar.
    """
    a = _normalizar_accion(accion)
    tipo = a.get("tipo")

    if tipo == "esperar":
        return True

    if tipo == "defensa":
        estado.jugador.defendiendo = True
        return True

    if tipo == "mover":
        d = a["direccion"]
        nr, nc = _celda_destino(entidad, d)
        sym = estado._get((nr, nc))

        estado._set(entidad.pos, estado.under_player if isinstance(entidad, Jugador) else EMPTY)
        entidad.r, entidad.c = nr, nc

        if isinstance(entidad, Jugador):
            if sym == KEY:
                estado.jugador.tiene_llave = True
                if estado.llave:
                    estado.llave.recogida = True
                estado.under_player = EMPTY
                if not silencioso:
                    print("  🗝 Recogiste la llave.")
            else:
                estado.under_player = sym

            estado._set(entidad.pos, PLAYER)

            if sym == DOOR and estado.jugador.tiene_llave:
                if not silencioso:
                    print("  ★ ¡Has cruzado la puerta con la llave! Nivel completado.")
                estado.nivel_terminado = True
                estado.victoria = True
        else:
            estado._set(entidad.pos, OGRE)
        return True

    if tipo == "atacar":
        d = a["direccion"]
        nr, nc = _celda_destino(entidad, d)

        if isinstance(entidad, Jugador):
            orco = estado.orco_en(nr, nc)
            if orco:
                orco.hp = max(round(orco.hp - 1.0, 1), 0.0)
                if not orco.vivo:
                    estado.board[nr][nc] = EMPTY
                    if not silencioso:
                        print(f"  ⚔  Orco {orco.idx} derrotado.")
                else:
                    if not silencioso:
                        print(f"  ⚔  Golpe al Orco {orco.idx}. HP: {orco.hp:.1f}")
        else:
            j = estado.jugador
            dmg = 0.5 if j.defendiendo else 1.0
            j.hp = max(round(j.hp - dmg, 1), 0.0)
            if not silencioso:
                print(f"  ⚔  Orco {entidad.idx} ataca. Daño: {dmg}  HP: {j.hp:.1f}/3.0")
            if not j.vivo:
                estado.nivel_terminado = True
                estado.victoria = False
        return True

    if tipo == "abrir":
        d = a["direccion"]
        nr, nc = _celda_destino(entidad, d)
        cofre = estado.cofre_en(nr, nc)
        if cofre:
            cofre.abierto = True
            estado.board[nr][nc] = EMPTY
            estado.jugador.oro += 1
            if not silencioso:
                print(f"  📦 ¡Cofre abierto! Oro: {estado.jugador.oro}")
        return True

    return False


def probar(estado: Estado, entidad, accion):
    """
    Devuelve un Estado hipotético resultante de aplicar la acción.
    NO toca el estado real. Si la acción es inválida, devuelve None.
    """
    info = validar(estado, entidad, accion)
    if not info["valida"]:
        return None

    estado_copia = copy.deepcopy(estado)
    entidad_copia = _resolver_entidad_en_copia(estado_copia, entidad)
    if entidad_copia is None:
        return None

    _aplicar_accion_en_estado(estado_copia, entidad_copia, accion, silencioso=True)
    return estado_copia


def _emitir_eventos_transicion(antes: Estado, despues: Estado, entidad_original, accion):
    a = _normalizar_accion(accion)
    tipo = a.get("tipo")

    if tipo == "mover" and isinstance(entidad_original, Jugador):
        if not antes.jugador.tiene_llave and despues.jugador.tiene_llave:
            print("  🗝 Recogiste la llave.")
        if not antes.nivel_terminado and despues.nivel_terminado and despues.victoria:
            print("  ★ ¡Has cruzado la puerta con la llave! Nivel completado.")
        return

    if tipo == "atacar":
        if isinstance(entidad_original, Jugador):
            nr, nc = _celda_destino(antes.jugador, a["direccion"])
            orco_antes = antes.orco_en(nr, nc)
            orco_despues = despues.orco_en(nr, nc)
            if orco_antes and orco_despues is None:
                print(f"  ⚔  Orco {orco_antes.idx} derrotado.")
            elif orco_antes and orco_despues:
                print(f"  ⚔  Golpe al Orco {orco_despues.idx}. HP: {orco_despues.hp:.1f}")
        else:
            dmg = round(antes.jugador.hp - despues.jugador.hp, 1)
            print(f"  ⚔  Orco {entidad_original.idx} ataca. Daño: {dmg}  HP: {despues.jugador.hp:.1f}/3.0")
        return

    if tipo == "abrir" and despues.jugador.oro > antes.jugador.oro:
        print(f"  📦 ¡Cofre abierto! Oro: {despues.jugador.oro}")


def ejecutar(estado: Estado, entidad, accion) -> bool:
    """
    Operación simbólica principal: valida, prueba y aplica.
    Si es inválida, no modifica el estado y devuelve False.
    """
    info = validar(estado, entidad, accion)
    if not info["valida"]:
        return False

    estado_antes = copy.deepcopy(estado)
    estado_probado = probar(estado, entidad, accion)
    if estado_probado is None:
        return False

    _emitir_eventos_transicion(estado_antes, estado_probado, entidad, accion)
    _copiar_estado(estado_probado, estado)
    return True


# ═══════════════════════════════════════════════════════════
#  IA DEL ORCO  (spec §4.1: si puede atacar ataca, sino se mueve)
# ═══════════════════════════════════════════════════════════

def turno_orcos(estado: Estado):
    """
    Cada orco hace UNA acción (spec):
      - Si ya está adyacente (4 dirs) → marca para combate.
      - Si no → intenta moverse un paso hacia el jugador usando la misma capa simbólica.
    """
    DELTAS_4 = [(-1,0),(1,0),(0,-1),(0,1)]
    DIR_POR_DELTA = {(-1,0): "arriba", (1,0): "abajo", (0,-1): "izquierda", (0,1): "derecha"}
    j = estado.jugador
    orco_atacante = None

    for orco in estado.orcos:
        if not orco.vivo or estado.nivel_terminado:
            continue

        jr, jc = j.pos
        ya_adj = any(orco.r + dr == jr and orco.c + dc == jc for dr, dc in DELTAS_4)

        if ya_adj:
            if orco_atacante is None:
                orco_atacante = orco
            continue

        mejor_delta = None
        mejor_dist = abs(orco.r - jr) + abs(orco.c - jc)
        for dr, dc in DELTAS_4:
            nr, nc = orco.r + dr, orco.c + dc
            if not estado._dentro(nr, nc):
                continue
            dist = abs(nr - jr) + abs(nc - jc)
            accion = crear_accion("mover", direccion=DIR_POR_DELTA[(dr, dc)])
            if validar(estado, orco, accion)["valida"] and dist < mejor_dist:
                mejor_dist = dist
                mejor_delta = (dr, dc)

        if mejor_delta:
            ejecutar(estado, orco, crear_accion("mover", direccion=DIR_POR_DELTA[mejor_delta]))

    j.defendiendo = False
    return orco_atacante


# ═══════════════════════════════════════════════════════════
#  PANTALLA DE COMBATE
# ═══════════════════════════════════════════════════════════

def _barra(valor, maximo, ancho):
    filled = round((max(valor, 0) / maximo) * ancho)
    return "[" + "█" * filled + "░" * (ancho - filled) + "]"


SPRITE_J     = ["   O   ", "  /|\\  ", "  / \\  "]
SPRITE_J_DEF = ["   O   ", " [/|   ", "  / \\  "]
SPRITE_O     = ["  >O<  ", " \\|/   ", "  / \\  "]
SPRITE_O_ATK = ["  >O<  ", " \\|/-- ", "  / \\  "]


def pantalla_combate(estado: Estado, orco: Orco, log: str = "", orco_ataca: bool = False):
    os.system("cls" if os.name == "nt" else "clear")
    j = estado.jugador
    W = 54

    sj = SPRITE_J_DEF if j.defendiendo else SPRITE_J
    so = SPRITE_O_ATK if orco_ataca    else SPRITE_O

    print("╔" + "═" * W + "╗")
    print("║" + "  ⚔  COMBATE  ⚔".center(W) + "║")
    print("╠" + "═" * W + "╣")
    print("║" + " " * W + "║")
    for lj, lo in zip(sj, so):
        print("║" + f"  {lj}              {lo}  ".ljust(W) + "║")
    print("║" + " " * W + "║")
    bj = _barra(j.hp,    3.0, 12)
    bo = _barra(orco.hp, 2.0, 12)
    print("║" + f"  Caballero {bj} {j.hp:.1f}/3.0   Oro: {j.oro}".ljust(W) + "║")
    print("║" + f"  Orco {orco.idx}    {bo} {orco.hp:.1f}/2.0".ljust(W) + "║")
    print("║" + " " * W + "║")
    print("╠" + "═" * W + "╣")
    print("║" + "  atacar  /  defensa".ljust(W) + "║")
    print("╠" + "═" * W + "╣")
    print("║" + (f"  {log}" if log else " ").ljust(W) + "║")
    print("╚" + "═" * W + "╝")


# ═══════════════════════════════════════════════════════════
#  LLM
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT_MAPA = """Eres un parser de comandos para un juego de dungeons.
Convierte la instrucción del jugador a JSON válido.
Sin texto extra, sin backticks, sin markdown.

ESQUEMAS:

1) Movimiento (siempre 1 sola celda, 1 solo paso):
{"accion":"mover","pasos":[{"direccion":"arriba","cantidad":1}]}

2) Moverse hacia el objeto más cercano:
{"accion":"mover","objetivo":"cofre"}

3) Abrir cofre adyacente:
{"accion":"abrir","direccion":"derecha"}

4) Esperar:
{"accion":"esperar"}

REGLAS:
- ir/ve/muévete/camina/avanza/desplázate → "mover"
- abrir/interactuar → "abrir" si el objetivo es un cofre
- si el jugador pide abrir o usar la puerta → {"accion":"mover","objetivo":"puerta"}
- esperar/pasar/descansar → "esperar"
- Direcciones válidas: arriba, abajo, izquierda, derecha, arriba-izquierda, arriba-derecha, abajo-izquierda, abajo-derecha
- Objetivos válidos: cofre, orco, puerta, llave
- Si hay objeto destino → formato 2. Si hay dirección → formato 1.
- IMPORTANTE: el movimiento es SIEMPRE de 1 sola celda. "cantidad" siempre vale 1.
- Si el jugador pide moverse múltiples pasos o en múltiples direcciones, interpretá solo el PRIMER paso con cantidad 1.
- Si no entendés: {"accion":"desconocido"}
- Solo JSON."""

SYSTEM_PROMPT_COMBATE = """Eres un parser de comandos de combate para un dungeon.
Convierte la instrucción a JSON válido. Sin texto extra ni backticks.

{"accion":"atacar"}
{"accion":"defensa"}
{"accion":"desconocido"}

- atacar: golpear, pegar, ataque, embisto, fight, attack
- defensa: defender, guardia, escudo, proteger, bloquear, block
- Solo JSON."""


def verificar_modelo():
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        print("\n  ✗ Ollama no está corriendo. Inicialo con: ollama serve\n")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        detalle = ""
        if e.response is not None:
            detalle = e.response.text.strip()
        if detalle:
            print(f"  Error HTTP de Ollama: {detalle}. Turno cancelado.")
        else:
            print(f"  Error HTTP de Ollama: {e}. Turno cancelado.")
        return None, False, None
    except requests.exceptions.RequestException as e:
        print(f"\n  ✗ Error conectando con Ollama: {e}\n")
        sys.exit(1)

    nombres    = [m.get("name", "").split(":")[0]
                  for m in resp.json().get("models", [])]
    modelo_base = OLLAMA_MODEL.split(":")[0]

    if modelo_base not in nombres:
        print(f"\n  ✗ Modelo '{OLLAMA_MODEL}' no instalado.")
        if nombres:
            print(f"    Disponibles: {', '.join(nombres)}")
        else:
            print(f"    Instalá con: ollama pull {OLLAMA_MODEL}")
        sys.exit(1)

    print(f"  ✔ Modelo '{OLLAMA_MODEL}' listo.\n")


def llamar_llm_con_metricas(texto: str, system_prompt: str) -> tuple[dict | None, bool, float | None]:
    """Llama al LLM y devuelve (data, json_valido, latencia_ms)."""
    try:
        t0 = time.perf_counter()
        resp = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "stream": False,
                  "system": system_prompt,
                  "prompt": f'Instrucción: "{texto}"'},
            timeout=30,
        )
        resp.raise_for_status()
        t_ms = (time.perf_counter() - t0) * 1000
        raw  = resp.json().get("response", "")
        print(f"  ⏱  {OLLAMA_MODEL}  {t_ms:.0f} ms")
        data, json_valido = _parsear_json_con_estado(raw)
        if not json_valido:
            print(f"  ⚠  JSON inválido: {raw[:80]!r}")
        return data, json_valido, t_ms
    except requests.exceptions.ConnectionError:
        print("  ✗ Ollama dejó de responder. Turno cancelado.")
        return None, False, None
    except requests.exceptions.Timeout:
        print("  ✗ Timeout. Turno cancelado.")
        return None, False, None
    except requests.exceptions.RequestException as e:
        print(f"  ✗ Error: {e}. Turno cancelado.")
        return None, False, None


def llamar_llm(texto: str, system_prompt: str) -> dict | None:
    """Llama al LLM. Sin fallback. Imprime latencia."""
    data, _, _ = llamar_llm_con_metricas(texto, system_prompt)
    return data


def _parsear_json(raw: str) -> dict:
    data, json_valido = _parsear_json_con_estado(raw)
    if not json_valido:
        print(f"  ⚠  JSON inválido: {raw[:80]!r}")
    return data


def _parsear_json_con_estado(raw: str) -> tuple[dict, bool]:
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            d = json.loads(match.group(0))
            if "accion" in d:
                return d, True
        except json.JSONDecodeError:
            pass
    return {"accion": "desconocido"}, False


# ═══════════════════════════════════════════════════════════
#  BUCLE DE COMBATE
# ═══════════════════════════════════════════════════════════

def combate(estado: Estado, orco: Orco, primer_ataque: str = "jugador"):
    """
    primer_ataque: "jugador" | "orco"
    Solo define quién actúa primero. NO aplica daño al abrir la pantalla.
    """
    j   = estado.jugador
    log = ("⚔ Vos iniciaste el contacto. Tenés la iniciativa."
           if primer_ataque == "jugador"
           else f"⚠ El Orco {orco.idx} te interceptó. Él tiene la iniciativa.")

    # Si el orco tiene iniciativa, su primer ataque va ANTES de que el jugador elija
    if primer_ataque == "orco":
        pantalla_combate(estado, orco, log=log, orco_ataca=True)
        input("\n  [ENTER para continuar]")
        dmg  = 0.5 if j.defendiendo else 1.0
        j.hp = max(round(j.hp - dmg, 1), 0.0)
        log  = f"⚔ Orco {orco.idx} golpeó primero. Daño: {dmg}. Tu HP: {j.hp:.1f}"
        pantalla_combate(estado, orco, log=log, orco_ataca=True)
        if not j.vivo:
            print("\n  ☠ Caíste. GAME OVER.")
            input("  [ENTER]")
            estado.nivel_terminado = True
            estado.victoria = False
            return
        input("\n  [ENTER para continuar]")

    while orco.vivo and j.vivo:
        j.defendiendo = False
        pantalla_combate(estado, orco, log=log, orco_ataca=False)

        try:
            texto = input("\n  Tu acción: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

        if not texto:
            continue

        print(f"  Interpretando: «{texto}»")
        data = llamar_llm(texto, SYSTEM_PROMPT_COMBATE)
        if data is None:
            log = "⚠ Modelo sin respuesta. Turno cancelado."
            continue

        accion = data.get("accion", "desconocido")

        if accion == "atacar":
            orco.hp = max(round(orco.hp - 1.0, 1), 0.0)
            if not orco.vivo:
                estado.board[orco.r][orco.c] = EMPTY
                log = f"⚔ ¡Orco {orco.idx} derrotado!"
                pantalla_combate(estado, orco, log=log)
                input("\n  [ENTER para continuar]")
                return
            else:
                log = f"⚔ Golpeaste al Orco {orco.idx}. HP: {orco.hp:.1f}"

        elif accion == "defensa":
            j.defendiendo = True
            log = "🛡 En guardia. Daño reducido a la mitad este turno."

        else:
            log = "❓ No entendí. Intentá: atacar o defensa."
            continue

        # Turno del orco
        if orco.vivo and j.vivo:
            dmg  = 0.5 if j.defendiendo else 1.0
            j.hp = max(round(j.hp - dmg, 1), 0.0)
            log += f"  |  Orco {orco.idx} contraatacó. Daño: {dmg}. HP: {j.hp:.1f}"
            pantalla_combate(estado, orco, log=log, orco_ataca=True)
            if not j.vivo:
                print("\n  ☠ Caíste. GAME OVER.")
                input("  [ENTER]")
                estado.nivel_terminado = True
                estado.victoria = False
                return


# ═══════════════════════════════════════════════════════════
#  INTÉRPRETE DE COMANDOS DEL MAPA
# ═══════════════════════════════════════════════════════════

OBJETIVO_MAP = {
    "cofre":  CHEST,
    "orco":   OGRE,
    "puerta": DOOR,
    "llave":  KEY,
}


def _mover_un_paso_hacia(estado: Estado, tr: int, tc: int) -> tuple[bool, bool]:
    """
    Mueve el jugador un paso hacia (tr,tc).
    Devuelve (movido, combate_iniciado).
    """
    j = estado.jugador
    if j.pos == (tr, tc):
        return False, False

    def score(r, c):
        return (max(abs(r - tr), abs(c - tc)), abs(r - tr) + abs(c - tc))

    mejor_score = score(j.r, j.c)
    mejor_dir = None

    for dir_str, (dr, dc) in DIRS_8.items():
        nr, nc = j.r + dr, j.c + dc
        if not estado._dentro(nr, nc):
            continue

        accion = crear_accion("mover", direccion=dir_str)
        if not validar(estado, j, accion)["valida"]:
            continue

        candidato_score = score(nr, nc)
        if candidato_score < mejor_score:
            mejor_score = candidato_score
            mejor_dir = dir_str

    if mejor_dir is None:
        return False, False

    ok = ejecutar(estado, j, crear_accion("mover", direccion=mejor_dir))
    return ok, False


def interpretar_y_ejecutar(estado: Estado, data: dict) -> bool:
    """
    Traduce el JSON del LLM a llamadas sobre el estado.
    Devuelve True si el turno fue consumido.
    """
    j      = estado.jugador
    accion = data.get("accion", "").lower().strip()

    # ── MOVER ─────────────────────────────────────────────
    if accion == "mover":

        # Hacia objetivo
        if "objetivo" in data:
            nombre  = str(data["objetivo"]).lower().strip()
            simbolo = OBJETIVO_MAP.get(nombre)
            if simbolo is None:
                print(f"  ✗ Objetivo desconocido: '{nombre}'.")
                return True

            target_pos, dist = estado.find_nearest(simbolo)
            if target_pos is None:
                print(f"  ✗ No hay '{nombre}' en el tablero.")
                return True

            tr, tc = target_pos
            print(f"  → Hacia '{nombre}' en ({tr},{tc}), dist {dist}")

            # 1 solo paso hacia el objetivo por turno (spec 4.3)
            if estado.jugador.pos == (tr, tc):
                print(f"  · Ya estás en '{nombre}'.")
                return True

            if max(abs(j.r - tr), abs(j.c - tc)) <= 1 and simbolo in (OGRE, CHEST):
                if simbolo == OGRE:
                    orco = estado.orco_en(tr, tc)
                    if orco:
                        print(f"  ⚔ Llegaste al orco. ¡Iniciando combate!")
                        combate(estado, orco, primer_ataque="jugador")
                        return True
                return True

            movido, cb = _mover_un_paso_hacia(estado, tr, tc)
            if cb:
                orco = estado.orco_en(tr, tc)
                if orco:
                    combate(estado, orco, primer_ataque="jugador")
            return True

        # Por pasos -- 1 sola celda por turno (spec 4.3: accion = celda contigua)
        elif "pasos" in data:
            pasos = data["pasos"]
            if not isinstance(pasos, list) or not pasos:
                print("  ✗ Campo 'pasos' inválido.")
                return True

            # Solo se ejecuta el primer paso con cantidad forzada a 1
            paso = pasos[0]
            if not isinstance(paso, dict):
                print("  ✗ Paso 1: formato inválido.")
                return True

            dir_raw  = str(paso.get("direccion", "")).lower().strip()
            cantidad = paso.get("cantidad", 1)

            if dir_raw not in DIRS_8:
                print(f"  ✗ Dirección inválida '{dir_raw}'")
                return True
            if not isinstance(cantidad, (int, float)) or int(cantidad) < 1:
                print(f"  ✗ Cantidad inválida '{cantidad}'")
                return True

            if len(pasos) > 1 or int(cantidad) > 1:
                print(f"  ℹ Solo se mueve 1 celda por turno → {dir_raw}")

            nr, nc = _celda_destino(j, dir_raw)
            sym = estado._get((nr, nc)) if estado._dentro(nr, nc) else None

            if sym == OGRE:
                orco = estado.orco_en(nr, nc)
                if orco:
                    print(f"  ⚔ ¡Contacto con orco! Iniciando combate.")
                    combate(estado, orco, primer_ataque="jugador")
                    return True

            ejecutar(estado, j, crear_accion("mover", direccion=dir_raw))
            return True

        else:
            print("  ✗ 'mover' sin objetivo ni pasos.")
            return True

    # ── ABRIR (solo cofres) ────────────────────────────────
    elif accion == "abrir":
        dir_raw  = str(data.get("direccion", "")).lower().strip()
        if dir_raw not in DIRS_4:
            print(f"  ✗ Solo se puede abrir en 4 direcciones cardinales.")
            return True
        if not validar(estado, j, {"tipo": "abrir", "direccion": dir_raw})["valida"]:
            nr, nc = _celda_destino(j, dir_raw)
            sym = estado._get((nr, nc)) if estado._dentro(nr, nc) else EMPTY
            if sym == OGRE:
                print(f"  ✗ Eso es un orco, no un cofre. Acercate para combatir.")
            elif sym == DOOR:
                print(f"  ✗ La puerta no se abre: se cruza caminando con la llave.")
            else:
                print(f"  ✗ No hay cofre en esa dirección.")
            return True
        return ejecutar(estado, j, crear_accion("abrir", direccion=dir_raw))

    # ── ESPERAR ───────────────────────────────────────────
    elif accion == "esperar":
        print("  · Turno pasado.")
        return True

    # ── DESCONOCIDO ───────────────────────────────────────
    elif accion == "desconocido":
        print("  ✗ No entendí. Ejemplos:")
        print("      ir 2 arriba")
        print("      ve al orco / ir al cofre / ve a la puerta")
        print("      abrir derecha")
        print("      esperar")
        return True

    else:
        print(f"  ✗ Acción no reconocida: '{accion}'")
        return True


# ═══════════════════════════════════════════════════════════
#  EVALUACIÓN MÍNIMA DE INTERPRETACIÓN
# ═══════════════════════════════════════════════════════════

EVAL_CASES = [
    # 8 movimientos simples — una por cada dirección, fraseología variada
    {"texto": "andá arriba",                        "esperado": {"accion": "mover", "pasos": [{"direccion": "arriba",           "cantidad": 1}]}},
    {"texto": "bajá",                               "esperado": {"accion": "mover", "pasos": [{"direccion": "abajo",            "cantidad": 1}]}},
    {"texto": "movete a la izquierda",              "esperado": {"accion": "mover", "pasos": [{"direccion": "izquierda",        "cantidad": 1}]}},
    {"texto": "ve a la derecha",                    "esperado": {"accion": "mover", "pasos": [{"direccion": "derecha",          "cantidad": 1}]}},
    {"texto": "subí en diagonal hacia la izquierda","esperado": {"accion": "mover", "pasos": [{"direccion": "arriba-izquierda", "cantidad": 1}]}},
    {"texto": "avanzá arriba a la derecha",         "esperado": {"accion": "mover", "pasos": [{"direccion": "arriba-derecha",   "cantidad": 1}]}},
    {"texto": "desplázate abajo-izquierda",         "esperado": {"accion": "mover", "pasos": [{"direccion": "abajo-izquierda",  "cantidad": 1}]}},
    {"texto": "caminá hacia abajo a la derecha",    "esperado": {"accion": "mover", "pasos": [{"direccion": "abajo-derecha",    "cantidad": 1}]}},

    # 4 objetivos — uno por cada target válido
    {"texto": "ve al orco",              "esperado": {"accion": "mover", "objetivo": "orco"}},
    {"texto": "andá al cofre más cercano","esperado": {"accion": "mover", "objetivo": "cofre"}},
    {"texto": "buscá la llave",          "esperado": {"accion": "mover", "objetivo": "llave"}},
    {"texto": "abrí la puerta",          "esperado": {"accion": "mover", "objetivo": "puerta"}},

    # 3 interacciones
    {"texto": "abrir derecha",                  "esperado": {"accion": "abrir",   "direccion": "derecha"}},
    {"texto": "abrí el cofre de la izquierda",  "esperado": {"accion": "abrir",   "direccion": "izquierda"}},
    {"texto": "esperar",                        "esperado": {"accion": "esperar"}},

    # 2 esperar con sinónimos
    {"texto": "pasar turno", "esperado": {"accion": "esperar"}},
    {"texto": "descansar",   "esperado": {"accion": "esperar"}},

    # 3 ambiguos / sin dirección clara
    {"texto": "hacé eso de antes",  "esperado": {"accion": "desconocido"}},
    {"texto": "andá para allá",     "esperado": {"accion": "desconocido"}},
    {"texto": "movete varios pasos","esperado": {"accion": "desconocido"}},

    # 2 fuera de dominio
    {"texto": "comprá una espada en la tienda",  "esperado": {"accion": "desconocido"}},
    {"texto": "cambiá el brillo de la pantalla", "esperado": {"accion": "desconocido"}},
]


EVAL_DIRECCIONES = {
    "arriba", "abajo", "izquierda", "derecha",
    "arriba-izquierda", "arriba-derecha",
    "abajo-izquierda", "abajo-derecha",
}
EVAL_DIRECCIONES_ABRIR = {"arriba", "abajo", "izquierda", "derecha"}
EVAL_OBJETIVOS = {"cofre", "orco", "puerta", "llave"}
EVAL_ACCIONES_MAPA = {"mover", "abrir", "esperar", "desconocido"}


def _canonical_eval(data: dict) -> dict:
    if not isinstance(data, dict):
        return {"accion": "desconocido"}

    accion = str(data.get("accion", "desconocido")).lower().strip()
    if accion == "mover" and "objetivo" in data:
        return {"accion": "mover", "objetivo": str(data["objetivo"]).lower().strip()}
    if accion == "mover" and "pasos" in data:
        pasos = []
        pasos_raw = data["pasos"] if isinstance(data["pasos"], list) else []
        for paso in pasos_raw:
            if not isinstance(paso, dict):
                continue
            try:
                cantidad = int(paso.get("cantidad", 1))
            except (TypeError, ValueError):
                cantidad = 1
            pasos.append({
                "direccion": str(paso.get("direccion", "")).lower().strip(),
                "cantidad": cantidad,
            })
        return {"accion": "mover", "pasos": pasos}
    if accion == "abrir":
        return {"accion": "abrir", "direccion": str(data.get("direccion", "")).lower().strip()}
    return {"accion": accion}


def _si_no(valor: bool) -> str:
    return "sí" if valor else "no"


def _respuesta_valida_mapa(data: dict) -> bool:
    if not isinstance(data, dict):
        return False

    accion = str(data.get("accion", "")).lower().strip()
    if accion not in EVAL_ACCIONES_MAPA:
        return False

    if accion == "mover":
        tiene_objetivo = "objetivo" in data
        tiene_pasos = "pasos" in data
        if tiene_objetivo == tiene_pasos:
            return False
        if tiene_objetivo:
            return str(data.get("objetivo", "")).lower().strip() in EVAL_OBJETIVOS

        pasos = data.get("pasos")
        if not isinstance(pasos, list) or len(pasos) == 0:
            return False
        for paso in pasos:
            if not isinstance(paso, dict):
                return False
            direccion = str(paso.get("direccion", "")).lower().strip()
            if direccion not in EVAL_DIRECCIONES:
                return False
            try:
                cantidad = int(paso.get("cantidad", 1))
            except (TypeError, ValueError):
                return False
            if cantidad < 1:
                return False
        return True

    if accion == "abrir":
        direccion = str(data.get("direccion", "")).lower().strip()
        return direccion in EVAL_DIRECCIONES_ABRIR

    if accion in ("esperar", "desconocido"):
        return True

    return False


def _cumple_intencion_general(obtenido: dict, esperado: dict) -> bool:
    accion_obtenida = obtenido.get("accion", "")
    accion_esperada = esperado.get("accion", "")
    if accion_obtenida != accion_esperada:
        return False

    if accion_esperada == "mover":
        if "objetivo" in esperado:
            return obtenido.get("objetivo", "") == esperado.get("objetivo", "")
        if "pasos" in esperado:
            return "pasos" in obtenido and len(obtenido["pasos"]) > 0
        return False

    if accion_esperada == "abrir":
        return "direccion" in obtenido

    return True


def _forma_optima(data: dict, esperado: dict) -> bool:
    if not isinstance(data, dict):
        return False

    accion = esperado.get("accion", "")

    if accion == "mover" and "objetivo" in esperado:
        return (
            set(data.keys()) == {"accion", "objetivo"}
            and _canonical_eval(data) == esperado
        )

    if accion == "mover" and "pasos" in esperado:
        pasos = data.get("pasos")
        if set(data.keys()) != {"accion", "pasos"}:
            return False
        if not isinstance(pasos, list) or len(pasos) != 1:
            return False
        paso = pasos[0]
        if not isinstance(paso, dict) or set(paso.keys()) != {"direccion", "cantidad"}:
            return False
        return _canonical_eval(data) == esperado

    if accion == "abrir":
        return set(data.keys()) == {"accion", "direccion"} and _canonical_eval(data) == esperado

    if accion in ("esperar", "desconocido"):
        return set(data.keys()) == {"accion"} and _canonical_eval(data) == esperado

    return False


def _evaluar_niveles(data: dict, json_valido: bool, esperado: dict) -> dict:
    obtenido = _canonical_eval(data)
    nivel_1 = json_valido and _respuesta_valida_mapa(data)
    nivel_2 = nivel_1 and _cumple_intencion_general(obtenido, esperado)
    nivel_3 = nivel_2 and _forma_optima(data, esperado)
    return {
        "obtenido": obtenido,
        "n1": nivel_1,
        "n2": nivel_2,
        "n3": nivel_3,
    }


def _etiqueta_resultado(niveles: dict, esperado: dict) -> str:
    es_rechazo = esperado.get("accion") == "desconocido"
    if niveles["n3"]:
        return "rechazo optimo" if es_rechazo else "respuesta optima"
    if niveles["n2"]:
        return "rechazo correcto" if es_rechazo else "cumple intencion general"
    if niveles["n1"]:
        return "JSON valido, no cumple intencion"
    return "respuesta invalida"


def _porcentaje(parte: int, total: int) -> float:
    return (parte / total * 100.0) if total > 0 else 0.0


def _evaluar_interpretacion_anterior():
    print("\nEVALUACIÓN MÍNIMA DE INTERPRETACIÓN")
    print(f"Modelo: {OLLAMA_MODEL}")
    print(f"Casos: {len(EVAL_CASES)}\n")

    total = len(EVAL_CASES)
    validos = 0
    correctos = 0
    perdidos = 0
    latencias = []

    for i, caso in enumerate(EVAL_CASES, 1):
        texto = caso["texto"]
        esperado = caso["esperado"]
        print(f"{i:02d}. Input: {texto!r}")
        data, json_valido, latencia_ms = llamar_llm_con_metricas(texto, SYSTEM_PROMPT_MAPA)
        data = data or {"accion": "desconocido"}
        obtenido = _canonical_eval(data)
        accion_correcta = json_valido and obtenido == esperado
        turno_perdido = (not json_valido) or (not accion_correcta)

        if not json_valido:
            motivo_perdido = "JSON inválido"
        elif obtenido.get("accion") == "desconocido":
            motivo_perdido = "acción desconocida"
        elif not accion_correcta:
            motivo_perdido = f"acción incorrecta (obtuvo {obtenido.get('accion')!r}, esperaba {esperado.get('accion')!r})"
        else:
            motivo_perdido = "—"

        validos += int(json_valido)
        correctos += int(accion_correcta)
        perdidos += int(turno_perdido)
        if latencia_ms is not None:
            latencias.append(latencia_ms)

        latencia_txt = f"{latencia_ms:.0f} ms" if latencia_ms is not None else "n/a"
        print(f"    Esperado: {esperado}")
        print(f"    Obtenido: {obtenido}")
        print(f"    JSON válido: {_si_no(json_valido)}")
        print(f"    Acción correcta: {_si_no(accion_correcta)}")
        print(f"    Latencia: {latencia_txt}")
        print(f"    Turno perdido: {_si_no(turno_perdido)}  ({motivo_perdido})\n")

    lat_media = sum(latencias) / len(latencias) if latencias else 0.0
    print("RESUMEN")
    print(f"  JSON válido: {validos / total * 100:.1f}%")
    print(f"  Acción correcta: {correctos / total * 100:.1f}%")
    print(f"  Latencia media: {lat_media:.0f} ms")
    print(f"  Turnos perdidos: {perdidos / total * 100:.1f}%\n")


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def evaluar_interpretacion():
    print("\nEVALUACION DE INTERPRETACION EN 3 NIVELES")
    print("N1: respuesta valida")
    print("N2: valida y cumple la intencion general")
    print("N3: valida, respeta la intencion y es la opcion optima")
    print(f"Modelo: {OLLAMA_MODEL}")
    print(f"Casos: {len(EVAL_CASES)}\n")

    total = len(EVAL_CASES)
    n1_total = 0
    n2_total = 0
    n3_total = 0
    accion_total = 0
    accion_n1 = 0
    accion_n2 = 0
    accion_n3 = 0
    rechazo_total = 0
    rechazo_n1 = 0
    rechazo_n2 = 0
    rechazo_n3 = 0
    latencias = []

    for i, caso in enumerate(EVAL_CASES, 1):
        texto = caso["texto"]
        esperado = caso["esperado"]
        es_rechazo = esperado.get("accion") == "desconocido"
        tipo_caso = "rechazo" if es_rechazo else "accion"

        print(f"Caso {i}/{total}: {texto}")
        data, json_valido, latencia_ms = llamar_llm_con_metricas(texto, SYSTEM_PROMPT_MAPA)
        data = data or {"accion": "desconocido"}
        niveles = _evaluar_niveles(data, json_valido, esperado)

        n1_total += int(niveles["n1"])
        n2_total += int(niveles["n2"])
        n3_total += int(niveles["n3"])

        if es_rechazo:
            rechazo_total += 1
            rechazo_n1 += int(niveles["n1"])
            rechazo_n2 += int(niveles["n2"])
            rechazo_n3 += int(niveles["n3"])
        else:
            accion_total += 1
            accion_n1 += int(niveles["n1"])
            accion_n2 += int(niveles["n2"])
            accion_n3 += int(niveles["n3"])

        if latencia_ms is not None:
            latencias.append(latencia_ms)

        latencia_txt = f"{latencia_ms:.0f} ms" if latencia_ms is not None else "n/a"
        etiqueta = _etiqueta_resultado(niveles, esperado)
        print(
            "  N1 %s | N2 %s | N3 %s | %s | %s | %s"
            % (
                _si_no(niveles["n1"]),
                _si_no(niveles["n2"]),
                _si_no(niveles["n3"]),
                latencia_txt,
                tipo_caso,
                etiqueta,
            )
        )
        print(f"    Esperado: {esperado}")
        print(f"    Obtenido: {niveles['obtenido']}\n")

    lat_media = sum(latencias) / len(latencias) if latencias else 0.0
    print("RESUMEN")
    print(f"  N1 respuesta valida: {n1_total}/{total} ({_porcentaje(n1_total, total):.1f}%)")
    print(f"  N2 intencion general: {n2_total}/{total} ({_porcentaje(n2_total, total):.1f}%)")
    print(f"  N3 respuesta optima: {n3_total}/{total} ({_porcentaje(n3_total, total):.1f}%)")
    print("  Acciones del juego:")
    print(f"    N1: {accion_n1}/{accion_total} ({_porcentaje(accion_n1, accion_total):.1f}%)")
    print(f"    N2: {accion_n2}/{accion_total} ({_porcentaje(accion_n2, accion_total):.1f}%)")
    print(f"    N3: {accion_n3}/{accion_total} ({_porcentaje(accion_n3, accion_total):.1f}%)")
    print("  Rechazos esperados:")
    print(f"    N1: {rechazo_n1}/{rechazo_total} ({_porcentaje(rechazo_n1, rechazo_total):.1f}%)")
    print(f"    N2 rechazo correcto: {rechazo_n2}/{rechazo_total} ({_porcentaje(rechazo_n2, rechazo_total):.1f}%)")
    print(f"    N3 rechazo optimo: {rechazo_n3}/{rechazo_total} ({_porcentaje(rechazo_n3, rechazo_total):.1f}%)")
    print(f"  Latencia media: {lat_media:.0f} ms\n")


AYUDA = """
╔══════════════════════════════════════════════════╗
║       DUNGEON KNIGHT  ·  Grilla 7×7              ║
╠══════════════════════════════════════════════════╣
║  Objetivo:                                       ║
║    1. Recogé la llave pisando su celda           ║
║    2. Caminá hacia la puerta con la llave        ║
║                                                  ║
║  Movimiento:                                     ║
║    ir 2 arriba  /  ve 3 derecha y 1 abajo        ║
║    ir al orco  /  ve al cofre  /  ir a la llave  ║
║                                                  ║
║  Interacción:                                    ║
║    abrir derecha   → abre cofre adyacente        ║
║    esperar         → pasa el turno               ║
║                                                  ║
║  Combate (pantalla automática al contacto):      ║
║    atacar  /  defensa                            ║
║                                                  ║
║  'ayuda' → este menú    'salir' → salir          ║
╚══════════════════════════════════════════════════╝
"""


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("--eval", "eval"):
        verificar_modelo()
        evaluar_interpretacion()
        return

    print(AYUDA)
    verificar_modelo()

    estado = Estado()

    while not estado.nivel_terminado:
        estado.print_board()

        try:
            texto = input("Comando: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nHasta luego.")
            sys.exit(0)

        if not texto:
            continue
        if texto.lower() in ("salir", "exit", "quit"):
            print("¡Hasta la próxima aventura!")
            break
        if texto.lower() in ("ayuda", "help", "?"):
            print(AYUDA)
            continue

        print(f"\n  Interpretando: «{texto}»")
        data = llamar_llm(texto, SYSTEM_PROMPT_MAPA)
        if data is None:
            print("  ↩ Turno cancelado.")
            continue

        turno_consumido = interpretar_y_ejecutar(estado, data)

        if estado.nivel_terminado:
            break

        if turno_consumido:
            orco_ataca = turno_orcos(estado)
            if orco_ataca and not estado.nivel_terminado:
                print(f"\n  ⚠ ¡Orco {orco_ataca.idx} se abalanza sobre vos!")
                combate(estado, orco_ataca, primer_ataque="orco")

        print()

    # Pantalla final
    if estado.nivel_terminado:
        estado.print_board()
        if estado.victoria:
            print("  ★━━━━━━━━━━━━━━━━━━━━━━━━━━★")
            print("  ★    ¡NIVEL COMPLETADO!     ★")
            print(f"  ★    Oro recogido: {estado.jugador.oro}           ★")
            print("  ★━━━━━━━━━━━━━━━━━━━━━━━━━━★\n")
        else:
            print("  ☠━━━━━━━━━━━━━━━━━━━━━━━━━━☠")
            print("  ☠        GAME  OVER         ☠")
            print("  ☠━━━━━━━━━━━━━━━━━━━━━━━━━━☠\n")


if __name__ == "__main__":
    main()
