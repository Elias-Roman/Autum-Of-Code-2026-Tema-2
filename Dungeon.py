import requests
import json
import re
import sys
import time
import os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# ═══════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════
SIZE         = 7
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL') or "mistral"

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
                    dist = abs(jr - r) + abs(jc - c)
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


def validar(estado: Estado, entidad, accion: dict) -> bool:
    """
    Devuelve True si la acción es realizable en el estado actual.
    NO modifica el estado.
    """
    tipo = accion.get("tipo")

    if tipo == "esperar":
        return True

    if tipo == "mover":
        d = accion.get("direccion")
        if d not in DIRS_8:
            return False
        nr, nc = _celda_destino(entidad, d)
        if not estado._dentro(nr, nc):
            return False
        sym = estado._get((nr, nc))
        # Puerta y llave no bloquean: se activan al pisarlas.
        if isinstance(entidad, Jugador):
            return sym in (EMPTY, DOOR, KEY)
        else:  # Orco: solo EMPTY
            return sym == EMPTY

    if tipo == "atacar":
        d = accion.get("direccion")
        if d not in DIRS_8:
            return False
        nr, nc = _celda_destino(entidad, d)
        if not estado._dentro(nr, nc):
            return False
        sym = estado._get((nr, nc))
        return sym == (OGRE if isinstance(entidad, Jugador) else PLAYER)

    if tipo == "abrir":
        d = accion.get("direccion")
        if d not in DIRS_4:
            return False
        nr, nc = _celda_destino(entidad, d)
        if not estado._dentro(nr, nc):
            return False
        sym = estado._get((nr, nc))
        return sym == CHEST   # solo cofres; la puerta se maneja al pisar

    if tipo == "defensa":
        return isinstance(entidad, Jugador)

    return False


def probar(estado: Estado, entidad, accion: dict) -> dict:
    """
    Devuelve un resumen del estado hipotético si se ejecutara la acción.
    NO modifica el estado real.
    """
    if not validar(estado, entidad, accion):
        return {"valida": False}

    tipo = accion.get("tipo")
    resultado = {"valida": True, "tipo": tipo}

    if tipo == "mover":
        nr, nc = _celda_destino(entidad, accion["direccion"])
        resultado["nueva_pos"] = (nr, nc)
        resultado["celda_destino"] = estado._get((nr, nc))

    if tipo == "atacar":
        nr, nc = _celda_destino(entidad, accion["direccion"])
        objetivo = estado.orco_en(nr, nc) if isinstance(entidad, Jugador) else None
        if objetivo:
            resultado["objetivo_hp_post"] = max(objetivo.hp - 1.0, 0)
            resultado["objetivo_muere"]   = objetivo.hp <= 1.0

    return resultado


# ═══════════════════════════════════════════════════════════
#  EJECUCIÓN SIMBÓLICA  (spec §4.4)
# ═══════════════════════════════════════════════════════════

def ejecutar_accion(estado: Estado, entidad, accion: dict) -> bool:
    """
    Ejecuta la acción sobre el estado.
    Acciones inválidas → se convierten en 'esperar' (spec: no falla, devuelve False).
    Devuelve True si se ejecutó la acción pedida, False si se convirtió en esperar.
    """
    if not validar(estado, entidad, accion):
        return False   # → esperar implícito

    tipo = accion.get("tipo")

    if tipo == "esperar":
        return True

    if tipo == "defensa":
        estado.jugador.defendiendo = True
        return True

    if tipo == "mover":
        d = accion["direccion"]
        nr, nc = _celda_destino(entidad, d)
        sym = estado._get((nr, nc))

        # ── Movimiento normal
        estado._set(entidad.pos, estado.under_player if isinstance(entidad, Jugador) else EMPTY)
        entidad.r, entidad.c = nr, nc
        if isinstance(entidad, Jugador):
            if sym == KEY:
                estado.jugador.tiene_llave = True
                if estado.llave:
                    estado.llave.recogida = True
                estado.under_player = EMPTY
                print("  🗝 Recogiste la llave.")
            else:
                estado.under_player = sym
            estado._set(entidad.pos, PLAYER)
            if sym == DOOR and estado.jugador.tiene_llave:
                print(f"  ★ ¡Has cruzado la puerta con la llave! Nivel completado.")
                estado.nivel_terminado = True
                estado.victoria = True
        else:
            estado._set(entidad.pos, OGRE)
        return True

    if tipo == "atacar":
        d = accion["direccion"]
        nr, nc = _celda_destino(entidad, d)

        if isinstance(entidad, Jugador):
            orco = estado.orco_en(nr, nc)
            if orco:
                orco.hp = max(round(orco.hp - 1.0, 1), 0.0)
                if not orco.vivo:
                    print(f"  ⚔  Orco {orco.idx} derrotado.")
                    estado.board[nr][nc] = EMPTY
                else:
                    print(f"  ⚔  Golpe al Orco {orco.idx}. HP: {orco.hp:.1f}")
        else:
            # Orco ataca jugador
            j   = estado.jugador
            dmg = 0.5 if j.defendiendo else 1.0
            j.hp = max(round(j.hp - dmg, 1), 0.0)
            print(f"  ⚔  Orco {entidad.idx} ataca. Daño: {dmg}  HP: {j.hp:.1f}/3.0")
            if not j.vivo:
                estado.nivel_terminado = True
                estado.victoria = False
        return True

    if tipo == "abrir":
        d = accion["direccion"]
        nr, nc = _celda_destino(entidad, d)
        cofre = estado.cofre_en(nr, nc)
        if cofre:
            cofre.abierto = True
            estado.board[nr][nc] = EMPTY
            estado.jugador.oro += 1
            print(f"  📦 ¡Cofre abierto! Oro: {estado.jugador.oro}")
        return True

    return True


# ═══════════════════════════════════════════════════════════
#  IA DEL ORCO  (spec §4.1: si puede atacar ataca, sino se mueve)
# ═══════════════════════════════════════════════════════════

def turno_orcos(estado: Estado):
    """
    Cada orco hace UNA acción (spec):
      - Si ya adyacente (4 dirs) → marca para combate (no aplica daño aquí).
      - Si no → se mueve un paso hacia el jugador (4 dirs).
        Aunque quede adyacente tras moverse, NO ataca ese mismo turno.
    Devuelve el orco que iniciará combate, o None.
    """
    DELTAS_4 = [(-1,0),(1,0),(0,-1),(0,1)]
    j = estado.jugador
    orco_atacante = None

    for orco in estado.orcos:
        if not orco.vivo or estado.nivel_terminado:
            continue

        jr, jc = j.pos
        ya_adj = any(orco.r + dr == jr and orco.c + dc == jc for dr, dc in DELTAS_4)

        if ya_adj:
            if orco_atacante is None:
                orco_atacante = orco   # solo el primero inicia combate
        else:
            # Moverse hacia el jugador
            mejor, mejor_dist = None, abs(orco.r - jr) + abs(orco.c - jc)
            for dr, dc in DELTAS_4:
                nr, nc = orco.r + dr, orco.c + dc
                if not estado._dentro(nr, nc) or estado.board[nr][nc] != EMPTY:
                    continue
                dist = abs(nr - jr) + abs(nc - jc)
                if dist < mejor_dist:
                    mejor_dist, mejor = dist, (dr, dc)
            if mejor:
                estado.board[orco.r][orco.c] = EMPTY
                orco.r += mejor[0]
                orco.c += mejor[1]
                estado.board[orco.r][orco.c] = OGRE

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

1) Movimiento por pasos:
{"accion":"mover","pasos":[{"direccion":"arriba","cantidad":2},{"direccion":"derecha","cantidad":3}]}

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
- Si hay objeto destino → formato 2. Si hay número/pasos → formato 1.
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
    dr = 0 if tr == j.r else (1 if tr > j.r else -1)
    dc = 0 if tc == j.c else (1 if tc > j.c else -1)

    # Dirección canónica (solo 4 dirs para simplicidad)
    if dr != 0 and dc != 0:
        # diagonal: preferir fila primero
        dc = 0

    dir_str = {(-1,0):"arriba",(1,0):"abajo",(0,-1):"izquierda",(0,1):"derecha"}.get((dr,dc))
    if not dir_str:
        return False, False

    nr, nc = j.r + dr, j.c + dc

    sym = estado._get((nr, nc))

    # Orco adyacente → combate, jugador tiene iniciativa
    if sym == OGRE:
        return True, True

    ok = ejecutar_accion(estado, j, {"tipo": "mover", "direccion": dir_str})
    return ok, False


def interpretar_y_ejecutar(estado: Estado, data: dict) -> str:
    """
    Traduce el JSON del LLM a llamadas sobre el estado.
    Devuelve:
      "consumido"  → acción válida ejecutada (turno gastado, orcos se mueven)
      "penalizado" → comando mal formado o mezclado (turno perdido, orcos se mueven)
      "fisico"     → acción sensata pero bloqueada por el mundo (sin penalización)
    """
    j      = estado.jugador
    accion = data.get("accion", "").lower().strip()

    # ── Detectar mezcla de acciones (mover + abrir, etc.) ─────────────────────
    # El LLM no debería devolver campos de distintas acciones en el mismo JSON.
    # Si "pasos" u "objetivo" coexiste con "direccion" de un abrir, es mezcla.
    tiene_pasos   = "pasos"   in data
    tiene_obj     = "objetivo" in data
    tiene_dir     = "direccion" in data

    if accion == "mover" and tiene_dir and not (tiene_pasos or tiene_obj):
        # "mover" con un campo "direccion" suelto sin pasos → mal formado
        print("  ✗ Comando mal formado: 'mover' necesita 'pasos' u 'objetivo'.")
        return "penalizado"

    if accion == "abrir" and (tiene_pasos or tiene_obj):
        # "abrir" mezclado con campos de mover
        print("  ✗ Comando mezclado: no se puede combinar 'abrir' con movimiento.")
        return "penalizado"

    # ── MOVER ─────────────────────────────────────────────
    if accion == "mover":

        # Hacia objetivo
        if "objetivo" in data:
            nombre  = str(data["objetivo"]).lower().strip()
            simbolo = OBJETIVO_MAP.get(nombre)
            if simbolo is None:
                print(f"  ✗ Objetivo desconocido: '{nombre}'.")
                return "penalizado"

            target_pos, dist = estado.find_nearest(simbolo)
            if target_pos is None:
                print(f"  ✗ No hay '{nombre}' en el tablero.")
                return "fisico"

            tr, tc = target_pos
            print(f"  → Hacia '{nombre}' en ({tr},{tc}), dist {dist}")

            # Avanzar paso a paso
            consumido = False
            for _ in range(SIZE * SIZE):
                if estado.jugador.pos == (tr, tc):
                    break
                if max(abs(j.r - tr), abs(j.c - tc)) <= 1 and simbolo in (OGRE, CHEST):
                    # Llegamos al lado → si es orco, combate
                    if simbolo == OGRE:
                        orco = estado.orco_en(tr, tc)
                        if orco:
                            print(f"  ⚔ Llegaste al orco. ¡Iniciando combate!")
                            combate(estado, orco, primer_ataque="jugador")
                            return "consumido"
                    break
                movido, cb = _mover_un_paso_hacia(estado, tr, tc)
                if cb:
                    orco = estado.orco_en(tr, tc)
                    if orco:
                        combate(estado, orco, primer_ataque="jugador")
                    return "consumido"
                if not movido or estado.nivel_terminado:
                    break
                consumido = True
            return "consumido" if consumido else "fisico"

        # Por pasos
        elif "pasos" in data:
            pasos = data["pasos"]
            if not isinstance(pasos, list) or not pasos:
                print("  ✗ Campo 'pasos' inválido.")
                return "penalizado"

            consumido = False
            for i, paso in enumerate(pasos, 1):
                if not isinstance(paso, dict):
                    continue
                dir_raw  = str(paso.get("direccion", "")).lower().strip()
                cantidad = paso.get("cantidad", 1)

                if dir_raw not in DIRS_8:
                    print(f"  ✗ Paso {i}: dirección inválida '{dir_raw}'")
                    continue
                if not isinstance(cantidad, (int, float)) or int(cantidad) < 1:
                    print(f"  ✗ Paso {i}: cantidad inválida '{cantidad}'")
                    continue

                print(f"  Paso {i}/{len(pasos)}: {int(cantidad)} → {dir_raw}")
                for _ in range(int(cantidad)):
                    nr, nc = _celda_destino(j, dir_raw)
                    sym = estado._get((nr, nc)) if estado._dentro(nr, nc) else None

                    # Choque con orco → combate con iniciativa del jugador
                    if sym == OGRE:
                        orco = estado.orco_en(nr, nc)
                        if orco:
                            print(f"  ⚔ ¡Contacto con orco! Iniciando combate.")
                            combate(estado, orco, primer_ataque="jugador")
                            return "consumido"

                    ok = ejecutar_accion(estado, j, {"tipo": "mover", "direccion": dir_raw})
                    if ok:
                        consumido = True
                    if not ok or estado.nivel_terminado:
                        break
                if estado.nivel_terminado:
                    return "consumido"
            return "consumido" if consumido else "fisico"

        else:
            print("  ✗ 'mover' sin objetivo ni pasos.")
            return "penalizado"

    # ── ABRIR (solo cofres) ────────────────────────────────
    elif accion == "abrir":
        dir_raw  = str(data.get("direccion", "")).lower().strip()
        if dir_raw not in DIRS_4:
            print(f"  ✗ Solo se puede abrir en 4 direcciones cardinales.")
            return "penalizado"
        if not validar(estado, j, {"tipo": "abrir", "direccion": dir_raw}):
            nr, nc = _celda_destino(j, dir_raw)
            sym = estado._get((nr, nc)) if estado._dentro(nr, nc) else EMPTY
            if sym == OGRE:
                print(f"  ✗ Eso es un orco, no un cofre. Acercate para combatir.")
            elif sym == DOOR:
                print(f"  ✗ La puerta no se abre: se cruza caminando con la llave.")
            else:
                print(f"  ✗ No hay cofre en esa dirección.")
            return "fisico"
        return "consumido" if ejecutar_accion(estado, j, {"tipo": "abrir", "direccion": dir_raw}) else "fisico"

    # ── ESPERAR ───────────────────────────────────────────
    elif accion == "esperar":
        print("  · Turno pasado.")
        return "consumido"

    # ── DESCONOCIDO ───────────────────────────────────────
    elif accion == "desconocido":
        print("  ✗ No entendí. Ejemplos:")
        print("      ir 2 arriba")
        print("      ve al orco / ir al cofre / ve a la puerta")
        print("      abrir derecha")
        print("      esperar")
        return "penalizado"

    else:
        print(f"  ✗ Acción no reconocida: '{accion}'")
        return "penalizado"


# ═══════════════════════════════════════════════════════════
#  EVALUACIÓN MÍNIMA DE INTERPRETACIÓN
# ═══════════════════════════════════════════════════════════

EVAL_CASES = [
    # 5 movimientos simples
    {"texto": "andá arriba", "esperado": {"accion": "mover", "pasos": [{"direccion": "arriba", "cantidad": 1}]}},
    {"texto": "movete dos casilleros a la derecha", "esperado": {"accion": "mover", "pasos": [{"direccion": "derecha", "cantidad": 2}]}},
    {"texto": "bajá 1", "esperado": {"accion": "mover", "pasos": [{"direccion": "abajo", "cantidad": 1}]}},
    {"texto": "caminá tres a la izquierda", "esperado": {"accion": "mover", "pasos": [{"direccion": "izquierda", "cantidad": 3}]}},
    {"texto": "subí en diagonal a la derecha", "esperado": {"accion": "mover", "pasos": [{"direccion": "arriba-derecha", "cantidad": 1}]}},

    # 5 movimientos compuestos
    {"texto": "andá 2 arriba y 1 derecha", "esperado": {"accion": "mover", "pasos": [{"direccion": "arriba", "cantidad": 2}, {"direccion": "derecha", "cantidad": 1}]}},
    {"texto": "bajá 1 y después movete 2 a la izquierda", "esperado": {"accion": "mover", "pasos": [{"direccion": "abajo", "cantidad": 1}, {"direccion": "izquierda", "cantidad": 2}]}},
    {"texto": "derecha derecha abajo", "esperado": {"accion": "mover", "pasos": [{"direccion": "derecha", "cantidad": 2}, {"direccion": "abajo", "cantidad": 1}]}},
    {"texto": "subí 1, izquierda 1 y bajá 1", "esperado": {"accion": "mover", "pasos": [{"direccion": "arriba", "cantidad": 1}, {"direccion": "izquierda", "cantidad": 1}, {"direccion": "abajo", "cantidad": 1}]}},
    {"texto": "avanzá 2 abajo-derecha y luego 1 arriba", "esperado": {"accion": "mover", "pasos": [{"direccion": "abajo-derecha", "cantidad": 2}, {"direccion": "arriba", "cantidad": 1}]}},

    # 3 objetivos
    {"texto": "ve al orco", "esperado": {"accion": "mover", "objetivo": "orco"}},
    {"texto": "andá al cofre más cercano", "esperado": {"accion": "mover", "objetivo": "cofre"}},
    {"texto": "buscá la llave", "esperado": {"accion": "mover", "objetivo": "llave"}},

    # 3 interacciones
    {"texto": "abrir derecha", "esperado": {"accion": "abrir", "direccion": "derecha"}},
    {"texto": "abrí el cofre de la izquierda", "esperado": {"accion": "abrir", "direccion": "izquierda"}},
    {"texto": "abrí la puerta", "esperado": {"accion": "mover", "objetivo": "puerta"}},

    # 2 ambiguos
    {"texto": "hacé eso de antes", "esperado": {"accion": "desconocido"}},
    {"texto": "andá para allá", "esperado": {"accion": "desconocido"}},

    # 2 fuera de dominio
    {"texto": "comprá una espada en la tienda", "esperado": {"accion": "desconocido"}},
    {"texto": "cambiá el brillo de la pantalla", "esperado": {"accion": "desconocido"}},
]


def _canonical_eval(data: dict) -> dict:
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


def evaluar_interpretacion():
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
        turno_perdido = (not json_valido) or obtenido.get("accion") == "desconocido"

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
        print(f"    Turno perdido: {_si_no(turno_perdido)}\n")

    lat_media = sum(latencias) / len(latencias) if latencias else 0.0
    print("RESUMEN")
    print(f"  JSON válido: {validos / total * 100:.1f}%")
    print(f"  Acción correcta: {correctos / total * 100:.1f}%")
    print(f"  Latencia media: {lat_media:.0f} ms")
    print(f"  Turnos perdidos: {perdidos / total * 100:.1f}%\n")


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

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

        resultado = interpretar_y_ejecutar(estado, data)
        # resultado: "consumido" | "penalizado" | "fisico"
        #   consumido  → acción válida ejecutada        → orcos se mueven
        #   penalizado → comando mal formado / mezclado → orcos se mueven, aviso
        #   fisico     → bloqueado por el mundo         → orcos NO se mueven

        if estado.nivel_terminado:
            break

        if resultado in ("consumido", "penalizado"):
            if resultado == "penalizado":
                print("  ⏳ Turno perdido. Los orcos se mueven.")
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