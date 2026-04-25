import random
import requests
import json
import re
import sys
import time
import os

# ═══════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════
SIZE         = 7
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "mistral"

# Símbolos del tablero (1 char para alineación perfecta)
PLAYER = "K"   # Caballero
CHEST  = "C"   # Cofre
OGRE   = "O"   # Orco
DOOR   = "D"   # Puerta (bloqueada)
KEY    = "Y"   # Llave
EMPTY  = "."

# ═══════════════════════════════════════════════════════════
#  ENTIDADES
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
    def __init__(self, r, c, idx=1, tiene_llave=False):
        self.r          = r
        self.c          = c
        self.hp         = float(random.choice([1, 2]))
        self.idx        = idx
        self.tiene_llave = tiene_llave   # al menos un orco porta la llave

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
        self.r        = r
        self.c        = c
        self.abierto  = False   # se abre solo si el jugador tiene la llave

    @property
    def pos(self): return (self.r, self.c)


# ═══════════════════════════════════════════════════════════
#  ESTADO DEL JUEGO
# ═══════════════════════════════════════════════════════════

class Game:
    def __init__(self):
        self.board        = [[EMPTY] * SIZE for _ in range(SIZE)]
        self.under_player = EMPTY

        self.jugador = None
        self.orcos   = []
        self.cofres  = []
        self.puerta  = None

        self.nivel_terminado = False
        self.victoria        = False

        self._generar_nivel()

    # ── helpers de posición ───────────────────────────────
    def _border_cells(self):
        cells = []
        for c in range(SIZE):
            cells += [(0, c), (SIZE - 1, c)]
        for r in range(1, SIZE - 1):
            cells += [(r, 0), (r, SIZE - 1)]
        return cells

    def _random_empty_border(self):
        opts = [p for p in self._border_cells() if self._get(p) == EMPTY]
        if not opts:
            raise RuntimeError("Sin celdas de borde libres para la puerta.")
        return random.choice(opts)

    def _random_empty_inner(self):
        for _ in range(10_000):
            r = random.randint(1, SIZE - 2)
            c = random.randint(1, SIZE - 2)
            if self.board[r][c] == EMPTY:
                return r, c
        raise RuntimeError("Sin celdas interiores libres.")

    def _place_many_inner(self, symbol, count):
        placed, attempts = 0, 0
        while placed < count and attempts < 1000:
            r = random.randint(0, SIZE - 1)
            c = random.randint(0, SIZE - 1)
            if self.board[r][c] == EMPTY:
                self.board[r][c] = symbol
                placed += 1
            attempts += 1

    # ── generación del nivel ──────────────────────────────
    def _generar_nivel(self):
        # Jugador
        r, c = self._random_empty_inner()
        self.jugador = Jugador(r, c)
        self.board[r][c] = PLAYER

        # Puerta bloqueada en el borde
        r, c = self._random_empty_border()
        self.puerta = Puerta(r, c)
        self.board[r][c] = DOOR

        # Orcos (1-2); el primero siempre porta la llave
        num_orcos = random.randint(1, 2)
        llave_asignada = False
        for i in range(1, num_orcos + 1):
            r, c = self._random_empty_inner()
            porta_llave = not llave_asignada   # el orco 1 siempre tiene la llave
            o = Orco(r, c, idx=i, tiene_llave=porta_llave)
            self.orcos.append(o)
            self.board[r][c] = OGRE
            if porta_llave:
                llave_asignada = True

        # Cofres (0-2)
        num_cofres = random.randint(0, 2)
        for _ in range(num_cofres):
            r, c = self._random_empty_inner()
            cf = Cofre(r, c)
            self.cofres.append(cf)
            self.board[r][c] = CHEST

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

    # ── visualización ─────────────────────────────────────
    def print_board(self):
        j = self.jugador
        orcos_vivos = [o for o in self.orcos if o.vivo]

        print("\n" + "─" * 44)
        hp_bar = _barra(j.hp, 3.0, 10)
        llave_str = "🗝 LLAVE" if j.tiene_llave else "  sin llave"
        print(f"  HP: {hp_bar} {j.hp:.1f}/3.0   Oro: {j.oro}   {llave_str}")
        for o in orcos_vivos:
            ob  = _barra(o.hp, 2.0, 10)
            lk  = " [🗝]" if o.tiene_llave else ""
            print(f"  Orco {o.idx}{lk}: {ob} {o.hp:.1f}  pos({o.r},{o.c})")
        puerta_str = "ABIERTA" if self.puerta.abierto else "BLOQUEADA"
        print(f"  Puerta: {puerta_str}  pos({self.puerta.r},{self.puerta.c})")
        print("─" * 44)

        print("      " + "  ".join(str(c) for c in range(SIZE)))
        sep = "    +" + "---" * SIZE + "--+"
        print(sep)
        for r, row in enumerate(self.board):
            print(f"  {r} | " + "  ".join(row) + "  |")
        print(sep)
        print(f"  K=Caballero  O=Orco  C=Cofre  D=Puerta  Y=Llave  .=Vacío")
        print(f"  Caballero → fila {j.r}, col {j.c}\n")

    # ── movimiento hacia objetivo ─────────────────────────
    def move_toward_target(self, symbol):
        target_pos, dist = self.find_nearest(symbol)
        if target_pos is None:
            print(f"  ✗ No hay '{symbol}' en el tablero.")
            return False, False   # (movido, combate_iniciado)

        tr, tc = target_pos
        print(f"  → Objetivo '{symbol}' en ({tr},{tc}), dist {dist}")

        steps = 0
        while True:
            pr, pc = self.jugador.pos

            if (pr, pc) == (tr, tc):
                break

            nr, nc = pr, pc
            if pr != tr:
                nr += 1 if pr < tr else -1
            elif pc != tc:
                nc += 1 if pc < tc else -1

            next_sym = self._get((nr, nc))

            # Llegaría al lado del orco → iniciar combate (jugador atacó primero)
            if (nr, nc) == (tr, tc) and next_sym == OGRE:
                print(f"  ✓ Llegaste junto al objetivo.")
                return True, True   # combate_iniciado = True

            # Llegaría al lado de cofre → detenerse
            if (nr, nc) == (tr, tc) and next_sym == CHEST:
                print(f"  ✓ Llegaste junto al cofre en ({pr},{pc}).")
                return True, False

            # Puerta cerrada en el camino → colisión
            if next_sym == DOOR and not self.puerta.abierto:
                print(f"  🔒 La puerta está bloqueada en ({nr},{nc}). Abrila primero con 'abrir <dirección>'.")
                return True, False

            # Bloqueado por otro objeto en el camino
            if next_sym in (OGRE, CHEST):
                print(f"  ! Camino bloqueado por '{next_sym}' en ({nr},{nc}).")
                return True, False

            # Moverse
            self._set(self.jugador.pos, self.under_player)
            self.jugador.r, self.jugador.c = nr, nc
            self.under_player = next_sym
            self._set(self.jugador.pos, PLAYER)
            steps += 1

            # Recoge llave si la pisa
            if next_sym == KEY:
                self._recoger_llave()

            # Entrar a la puerta abierta
            if next_sym == DOOR:
                print(f"  ★ ¡Has salido del calabozo por la puerta! ★")
                self.nivel_terminado = True
                self.victoria = True
                return True, False

            if steps > SIZE * SIZE * 2:
                print("  ✗ No se pudo alcanzar el objetivo.")
                return True, False

        return True, False

    # ── movimiento por pasos ──────────────────────────────
    def move_steps(self, direction, amount):
        ALIAS  = {"norte": "arriba", "sur": "abajo",
                  "oeste": "izquierda", "este": "derecha"}
        direction = ALIAS.get(direction, direction)
        VALIDAS = {"arriba", "abajo", "izquierda", "derecha"}
        if direction not in VALIDAS:
            print(f"  ✗ Dirección inválida: '{direction}'")
            return False, False

        moved = 0
        combate_iniciado = False

        for _ in range(amount):
            pr, pc = self.jugador.pos
            nr, nc = pr, pc

            if   direction == "arriba"    and pr > 0:        nr -= 1
            elif direction == "abajo"     and pr < SIZE - 1: nr += 1
            elif direction == "izquierda" and pc > 0:        nc -= 1
            elif direction == "derecha"   and pc < SIZE - 1: nc += 1
            else:
                print(f"  ! Límite del mapa en ({pr},{pc}).")
                break

            next_sym = self._get((nr, nc))

            # Intentar entrar a celda con orco → combate (jugador atacó primero)
            if next_sym == OGRE:
                print(f"  ⚔ ¡Entraste en contacto con un orco!")
                combate_iniciado = True
                break

            # Bloqueado por cofre
            if next_sym == CHEST:
                print(f"  ! Bloqueado por cofre en ({nr},{nc}). Usá 'abrir'.")
                break

            # Puerta cerrada → colisión, no se puede pisar
            if next_sym == DOOR and not self.puerta.abierto:
                print(f"  🔒 La puerta está bloqueada. Abrila primero con 'abrir <dirección>'.")
                break

            self._set(self.jugador.pos, self.under_player)
            self.jugador.r, self.jugador.c = nr, nc
            self.under_player = next_sym
            self._set(self.jugador.pos, PLAYER)
            moved += 1

            # Recoge llave si la pisa
            if next_sym == KEY:
                self._recoger_llave()

            # Entrar a la puerta (solo si está abierta, chequeado arriba)
            if next_sym == DOOR:
                print(f"  ★ ¡Has salido del calabozo por la puerta! ★")
                self.nivel_terminado = True
                self.victoria = True
                break

        if moved:
            print(f"  ✓ Movido {moved} paso(s) {direction} → ({self.jugador.r},{self.jugador.c})")
        return moved > 0 or combate_iniciado, combate_iniciado

    # ── abrir cofre o puerta ──────────────────────────────
    def abrir_en(self, direction):
        ALIAS  = {"norte": "arriba", "sur": "abajo",
                  "oeste": "izquierda", "este": "derecha"}
        direction = ALIAS.get(direction, direction)
        DELTAS_4 = {"arriba": (-1,0), "abajo": (1,0),
                    "izquierda": (0,-1), "derecha": (0,1)}

        if direction not in DELTAS_4:
            print(f"  ✗ Solo se puede abrir en 4 direcciones cardinales.")
            return False

        dr, dc = DELTAS_4[direction]
        nr, nc = self.jugador.r + dr, self.jugador.c + dc

        if not self._dentro(nr, nc):
            print("  ✗ Fuera del tablero.")
            return False

        sym = self._get((nr, nc))

        if sym == CHEST:
            cofre = self.cofre_en(nr, nc)
            if cofre:
                cofre.abierto = True
                self.board[nr][nc] = EMPTY
                self.jugador.oro += 1
                print(f"  📦 ¡Cofre abierto! Oro total: {self.jugador.oro}")
                return True

        if sym == DOOR:
            if not self.jugador.tiene_llave:
                print(f"  🔒 La puerta está bloqueada. Necesitás la llave.")
                print(f"     Buscá al orco que la tiene y derrótalo primero.")
                return False
            self.puerta.abierto = True
            self.board[nr][nc] = DOOR   # símbolo igual pero lógicamente abierta
            print(f"  🚪 ¡Puerta abierta con la llave! Movete hacia ella para salir.")
            return True

        if sym == KEY:
            self._recoger_llave()
            return True

        print(f"  ✗ No hay nada que abrir en esa dirección (hay '{sym}').")
        return False

    # ── recoger llave ─────────────────────────────────────
    def _recoger_llave(self):
        self.jugador.tiene_llave = True
        print(f"  🗝  ¡Recogiste la llave! Ahora podés abrir la puerta.")

    # ── turno de la IA de los orcos ───────────────────────
    def turno_orcos(self):
        """
        Cada orco hace UNA sola acción por turno:
          - Si ya está adyacente al jugador → inicia combate (orco tiene prioridad).
          - Si no está adyacente → se mueve un paso hacia el jugador.
            Si tras moverse queda adyacente, el combate ocurrirá en el SIGUIENTE turno
            (el movimiento agotó su acción).
        Devuelve el orco que iniciará combate, o None.
        """
        DELTAS_4 = [(-1,0),(1,0),(0,-1),(0,1)]
        j = self.jugador
        orco_atacante = None

        for orco in self.orcos:
            if not orco.vivo or self.nivel_terminado:
                continue

            jr, jc = j.pos
            ya_adyacente = any(
                orco.r + dr == jr and orco.c + dc == jc
                for dr, dc in DELTAS_4
            )

            if ya_adyacente:
                # Acción de este turno: ATACAR (iniciar combate)
                # Solo el primer orco adyacente inicia combate por turno
                if orco_atacante is None:
                    orco_atacante = orco
                # Los demás orcos adyacentes esperan (ya consumieron su turno)
            else:
                # Acción de este turno: MOVER un paso hacia el jugador
                mejor_dir  = None
                mejor_dist = abs(orco.r - jr) + abs(orco.c - jc)
                for dr, dc in DELTAS_4:
                    nr, nc = orco.r + dr, orco.c + dc
                    if not self._dentro(nr, nc):
                        continue
                    if self.board[nr][nc] != EMPTY:
                        continue
                    dist = abs(nr - jr) + abs(nc - jc)
                    if dist < mejor_dist:
                        mejor_dist = dist
                        mejor_dir  = (dr, dc)

                if mejor_dir:
                    dr, dc = mejor_dir
                    self.board[orco.r][orco.c] = EMPTY
                    orco.r += dr
                    orco.c += dc
                    self.board[orco.r][orco.c] = OGRE
                    # El movimiento agotó su turno; aunque ahora esté adyacente,
                    # NO ataca hasta el próximo turno.

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


def pantalla_combate(game: Game, orco: Orco, log: str = "", orco_ataca: bool = False):
    os.system("cls" if os.name == "nt" else "clear")
    j = game.jugador
    W = 54

    sj = SPRITE_J_DEF if j.defendiendo else SPRITE_J
    so = SPRITE_O_ATK if orco_ataca    else SPRITE_O

    print("╔" + "═" * W + "╗")
    print("║" + "  ⚔  COMBATE  ⚔".center(W) + "║")
    print("╠" + "═" * W + "╣")
    print("║" + " " * W + "║")
    for lj, lo in zip(sj, so):
        linea = f"  {lj}              {lo}  "
        print("║" + linea.ljust(W) + "║")
    print("║" + " " * W + "║")

    bj = _barra(j.hp,    3.0, 12)
    bo = _barra(orco.hp, 2.0, 12)
    lk = "  [tiene llave]" if orco.tiene_llave else ""
    print("║" + f"  Caballero {bj} {j.hp:.1f}/3.0   Oro: {j.oro}".ljust(W) + "║")
    print("║" + f"  Orco {orco.idx}    {bo} {orco.hp:.1f}/2.0{lk}".ljust(W) + "║")
    print("║" + " " * W + "║")
    print("╠" + "═" * W + "╣")
    print("║" + "  Opciones (en lenguaje natural):".ljust(W) + "║")
    print("║" + "    atacar  /  golpear  /  pegar".ljust(W) + "║")
    print("║" + "    defensa  /  guardia  /  escudo".ljust(W) + "║")
    print("║" + "    huir  /  escapar  /  retroceder".ljust(W) + "║")
    print("╠" + "═" * W + "╣")
    msg = f"  {log}" if log else " "
    print("║" + msg.ljust(W) + "║")
    print("╚" + "═" * W + "╝")


# ═══════════════════════════════════════════════════════════
#  LLM
# ═══════════════════════════════════════════════════════════

SYSTEM_PROMPT_MAPA = """Eres un parser de comandos para un juego de dungeons.
Convierte la instrucción del jugador a JSON válido.
Sin texto extra, sin backticks, sin markdown.

ESQUEMAS:

1) Movimiento por pasos (uno o varios encadenados):
{"accion":"mover","pasos":[{"direccion":"arriba","cantidad":2},{"direccion":"derecha","cantidad":3}]}

2) Movimiento hacia el objeto más cercano:
{"accion":"mover","objetivo":"cofre"}

3) Abrir objeto adyacente:
{"accion":"abrir","direccion":"derecha"}

4) Esperar:
{"accion":"esperar"}

REGLAS:
- Verbos de movimiento (ir, ve, muévete, camina, avanza, desplázate, etc.) → "mover".
- Abrir/interactuar/usar → "abrir".
- Esperar/pasar/descansar → "esperar".
- Direcciones válidas: arriba, abajo, izquierda, derecha, norte, sur, este, oeste.
- Objetivos válidos: cofre, orco, ogro, puerta, salida, llave.
- Si mencionan un objeto destino → formato 2.
- Si mencionan pasos/casillas/número → formato 1.
- Si no entiendes: {"accion":"desconocido"}
- Solo JSON."""

SYSTEM_PROMPT_COMBATE = """Eres un parser de comandos para un combate en un juego de dungeons.
El jugador está peleando contra un orco. Convierte su instrucción a JSON válido.
Sin texto extra, sin backticks, sin markdown.

ESQUEMAS POSIBLES:
{"accion":"atacar"}
{"accion":"defensa"}
{"accion":"huir"}
{"accion":"desconocido"}

REGLAS:
- atacar: golpear, pegar, ataque, hiero, embisto, lucho, peleo, fight, attack, golpe
- defensa: defender, defenderse, guardia, escudo, proteger, bloquear, block, me defiendo
- huir: escapar, huida, retroceder, salir, flee, run, retirada, me voy, corro
- Si no reconocés el comando: {"accion":"desconocido"}
- Responde SOLO con el JSON."""


def verificar_modelo():
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        print("\n  ✗ ERROR: Ollama no está corriendo.")
        print("    Inicialo con:  ollama serve")
        print("    El juego requiere el modelo LLM para funcionar.\n")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"\n  ✗ ERROR al conectar con Ollama: {e}\n")
        sys.exit(1)

    modelos_raw = resp.json().get("models", [])
    nombres     = [m.get("name", "").split(":")[0] for m in modelos_raw]
    modelo_base = OLLAMA_MODEL.split(":")[0]

    if modelo_base not in nombres:
        print(f"\n  ✗ ERROR: El modelo '{OLLAMA_MODEL}' no está instalado.")
        if nombres:
            print(f"    Modelos disponibles: {', '.join(nombres)}")
            print(f"    Cambiá OLLAMA_MODEL en el código por uno de esos.")
        else:
            print(f"    No hay ningún modelo. Instalá con:  ollama pull {OLLAMA_MODEL}")
        print("    El juego no puede continuar sin el modelo LLM.\n")
        sys.exit(1)

    print(f"  ✔ Modelo '{OLLAMA_MODEL}' verificado y listo.\n")


def llamar_llm(texto: str, system_prompt: str) -> dict | None:
    """Llama al LLM sin fallback. Imprime tiempo de respuesta."""
    try:
        t0 = time.perf_counter()
        resp = requests.post(
            OLLAMA_URL,
            json={
                "model":  OLLAMA_MODEL,
                "stream": False,
                "system": system_prompt,
                "prompt": f'Instrucción: "{texto}"',
            },
            timeout=30,
        )
        resp.raise_for_status()
        t_ms = (time.perf_counter() - t0) * 1000
        raw  = resp.json().get("response", "")
        print(f"  ⏱  Modelo: {OLLAMA_MODEL}  |  {t_ms:.0f} ms")
        return _parsear_json(raw)

    except requests.exceptions.ConnectionError:
        print(f"\n  ✗ Ollama dejó de responder. Turno cancelado.\n")
        return None
    except requests.exceptions.Timeout:
        print(f"\n  ✗ Timeout ({OLLAMA_MODEL}). Turno cancelado.\n")
        return None
    except requests.exceptions.RequestException as e:
        print(f"\n  ✗ Error de red: {e}. Turno cancelado.\n")
        return None


def _parsear_json(raw: str) -> dict:
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if "accion" in data:
                return data
        except json.JSONDecodeError:
            pass
    print(f"  ⚠  JSON inválido del modelo → raw: {raw[:100]!r}")
    return {"accion": "desconocido"}


# ═══════════════════════════════════════════════════════════
#  BUCLE DE COMBATE
#  primer_ataque: "jugador" → jugador ataca primero
#                 "orco"    → orco ataca primero
# ═══════════════════════════════════════════════════════════

def combate(game: Game, orco: Orco, primer_ataque: str = "jugador"):
    """
    Pantalla de combate por lenguaje natural.
    primer_ataque: "jugador" → jugador actúa primero en el bucle.
                   "orco"    → se muestra aviso de que el orco inició, pero NO se aplica daño.
                               El orco tendrá prioridad al final del primer turno del jugador.
    Entrar al combate nunca baja HP por sí solo; solo define el orden.
    """
    j   = game.jugador
    log = ""

    # Aviso de quién inició el contacto (sin daño)
    if primer_ataque == "orco":
        log = f"⚠ ¡El Orco {orco.idx} te interceptó! Tiene la iniciativa este turno."
    else:
        log = f"⚔ ¡Iniciaste el combate! Tenés la iniciativa este turno."

    # ── Bucle principal ───────────────────────────────────
    while orco.vivo and j.vivo:
        j.defendiendo = False
        pantalla_combate(game, orco, log=log, orco_ataca=False)

        try:
            texto = input("\n  Tu acción: ").strip()
        except (EOFError, KeyboardInterrupt):
            sys.exit(0)

        if not texto:
            continue

        print(f"\n  Interpretando: «{texto}»")
        data = llamar_llm(texto, SYSTEM_PROMPT_COMBATE)
        if data is None:
            log = "⚠ El modelo no respondió. Turno cancelado."
            continue

        accion = data.get("accion", "desconocido")

        # ── ATACAR ────────────────────────────────────────
        if accion == "atacar":
            orco.hp = round(orco.hp - 1.0, 1)
            if not orco.vivo:
                # Soltar llave si el orco la tenía
                if orco.tiene_llave:
                    orco.tiene_llave = False
                    game.jugador.tiene_llave = True
                    game.board[orco.r][orco.c] = EMPTY
                    log = f"⚔ ¡Golpe final! Orco {orco.idx} derrotado. Recogiste la 🗝 LLAVE."
                else:
                    game.board[orco.r][orco.c] = EMPTY
                    log = f"⚔ ¡Golpe final! Orco {orco.idx} derrotado."
                pantalla_combate(game, orco, log=log, orco_ataca=False)
                input("\n  [ENTER para continuar]")
                return
            else:
                log = f"⚔ Golpeaste al Orco {orco.idx}. HP restante: {orco.hp:.1f}"

        # ── DEFENSA ───────────────────────────────────────
        elif accion == "defensa":
            j.defendiendo = True
            log = "🛡 En guardia. El próximo daño se reduce a la mitad."

        # ── HUIR ──────────────────────────────────────────
        elif accion == "huir":
            DELTAS_4   = [(-1,0),(1,0),(0,-1),(0,1)]
            dr_h = j.r - orco.r
            dc_h = j.c - orco.c
            dr_n = 0 if dr_h == 0 else (1 if dr_h > 0 else -1)
            dc_n = 0 if dc_h == 0 else (1 if dc_h > 0 else -1)

            huido      = False
            candidatos = [(dr_n, dc_n)] + [d for d in DELTAS_4 if d != (-dr_n, -dc_n)]
            for dr, dc in candidatos:
                nr, nc = j.r + dr, j.c + dc
                if game._dentro(nr, nc) and game.board[nr][nc] == EMPTY:
                    game._set(j.pos, game.under_player)
                    j.r, j.c       = nr, nc
                    game.under_player = EMPTY
                    game._set(j.pos, PLAYER)
                    huido = True
                    break

            if huido:
                pantalla_combate(game, orco, log=f"💨 Huiste. Caballero en ({j.r},{j.c}).", orco_ataca=False)
                input("\n  [ENTER para continuar]")
                return
            else:
                log = "⛔ No hay escapatoria. Estás acorralado."
                continue

        # ── DESCONOCIDO ───────────────────────────────────
        else:
            log = "❓ No entendí. Intentá: 'atacar', 'defensa' o 'huir'."
            continue

        # ── TURNO DEL ORCO ────────────────────────────────
        # Si el orco inició el contacto, ataca ANTES de que el jugador pueda actuar
        # en la primera iteración (prioridad del orco en ronda 1).
        if orco.vivo and j.vivo:
            # En ronda 1 con prioridad del orco: el orco ya "atacó" al moverse,
            # así que en esta primera iteración el orco contraataca normalmente.
            dmg  = 0.5 if j.defendiendo else 1.0
            j.hp = max(round(j.hp - dmg, 1), 0.0)   # HP nunca baja de 0
            log += f"  |  Orco {orco.idx} contraatacó! Daño: {dmg}. Tu HP: {j.hp:.1f}"
            pantalla_combate(game, orco, log=log, orco_ataca=True)

            if not j.vivo:
                print("\n  ☠ El caballero ha caído. GAME OVER.")
                input("  [ENTER para continuar]")
                game.nivel_terminado = True
                game.victoria = False
                return


# ═══════════════════════════════════════════════════════════
#  EJECUTOR DE ACCIONES EN EL MAPA
# ═══════════════════════════════════════════════════════════

ACCIONES_MOVER = {
    "mover", "ir", "ve", "muévete", "muevete", "caminar",
    "camina", "desplazarse", "avanzar", "avanza",
}

OBJETIVO_MAP = {
    "cofre":  CHEST,  "cofres": CHEST,
    "orco":   OGRE,   "orcos":  OGRE,
    "ogro":   OGRE,   "ogros":  OGRE,
    "puerta": DOOR,   "salida": DOOR,
    "llave":  KEY,
}

DIRECCIONES_VALIDAS = {"arriba", "abajo", "izquierda", "derecha",
                       "norte",  "sur",   "oeste",     "este"}
DIRECCION_ALIAS     = {"norte": "arriba", "sur": "abajo",
                       "oeste": "izquierda", "este": "derecha"}


def ejecutar(game: Game, data: dict) -> bool:
    """
    Ejecuta la acción del jugador en el mapa.
    Devuelve True si el turno fue consumido.
    """
    accion = data.get("accion", "").lower().strip()
    if accion in ACCIONES_MOVER:
        accion = "mover"

    # ── MOVER ─────────────────────────────────────────────
    if accion == "mover":
        if "objetivo" in data:
            nombre  = str(data["objetivo"]).lower().strip()
            simbolo = OBJETIVO_MAP.get(nombre)
            if simbolo is None:
                print(f"  ✗ Objetivo desconocido: '{nombre}'. Válidos: {', '.join(OBJETIVO_MAP)}")
                return False

            movido, combate_iniciado = game.move_toward_target(simbolo)

            if combate_iniciado:
                # Jugador se acercó → él ataca primero
                target_pos, _ = game.find_nearest(OGRE)
                if target_pos:
                    orco = game.orco_en(*target_pos)
                    if orco:
                        combate(game, orco, primer_ataque="jugador")
            return movido

        elif "pasos" in data:
            pasos = data["pasos"]
            if not isinstance(pasos, list) or not pasos:
                print("  ✗ Campo 'pasos' inválido.")
                return False

            consumido = False
            for i, paso in enumerate(pasos, 1):
                if not isinstance(paso, dict):
                    continue

                dir_raw  = str(paso.get("direccion", "")).lower().strip()
                cantidad = paso.get("cantidad", 1)
                dir_norm = DIRECCION_ALIAS.get(dir_raw, dir_raw)

                if dir_norm not in DIRECCIONES_VALIDAS:
                    print(f"  ✗ Paso {i}: dirección inválida '{dir_raw}'")
                    continue
                if not isinstance(cantidad, (int, float)) or int(cantidad) < 1:
                    print(f"  ✗ Paso {i}: cantidad inválida '{cantidad}'")
                    continue

                print(f"  Paso {i}/{len(pasos)}: {int(cantidad)} → {dir_norm}")
                movido, combate_iniciado = game.move_steps(dir_norm, int(cantidad))

                if movido:
                    consumido = True
                if game.nivel_terminado:
                    return True

                if combate_iniciado:
                    # Jugador chocó contra orco → jugador atacó primero
                    j = game.jugador
                    DELTAS_4 = [(-1,0),(1,0),(0,-1),(0,1)]
                    for dr, dc in DELTAS_4:
                        orco = game.orco_en(j.r + dr, j.c + dc)
                        if orco:
                            combate(game, orco, primer_ataque="jugador")
                            break
                    return True

            return consumido
        else:
            print("  ✗ 'mover' sin objetivo ni pasos.")
            return False

    # ── ABRIR ─────────────────────────────────────────────
    elif accion == "abrir":
        dir_raw  = str(data.get("direccion", "")).lower().strip()
        dir_norm = DIRECCION_ALIAS.get(dir_raw, dir_raw)
        return game.abrir_en(dir_norm)

    # ── ESPERAR ───────────────────────────────────────────
    elif accion == "esperar":
        print("  · Turno pasado.")
        return True

    # ── DESCONOCIDO ───────────────────────────────────────
    elif accion == "desconocido":
        print("  ✗ No entendí. Ejemplos:")
        print("      ir 2 arriba")
        print("      ve 3 derecha y luego 1 abajo")
        print("      ir al orco / ir al cofre / ir a la llave")
        print("      abrir derecha")
        print("      esperar")
        return False
    else:
        print(f"  ✗ Acción no soportada: '{accion}'")
        return False


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

AYUDA = """
╔════════════════════════════════════════════════╗
║      DUNGEON KNIGHT  ·  Grilla 7×7             ║
╠════════════════════════════════════════════════╣
║  Movimiento:                                   ║
║    ir 2 arriba                                 ║
║    ve 3 derecha y luego 1 abajo                ║
║    ir al cofre / al orco / a la llave          ║
║    ve a la puerta                              ║
║                                                ║
║  Interacción:                                  ║
║    abrir derecha  →  abre cofre o puerta       ║
║    esperar        →  pasa el turno             ║
║                                                ║
║  Objetivo del nivel:                           ║
║    1. Derrotar al orco que tiene la 🗝 LLAVE   ║
║    2. Abrir la puerta con 'abrir <dirección>'  ║
║    3. Entrar a la puerta para ganar            ║
║                                                ║
║  Combate (pantalla automática):                ║
║    atacar  /  defensa  /  huir                 ║
║    Quien inicia el contacto ataca primero.     ║
║                                                ║
║  'ayuda' → este menú    'salir' → salir        ║
╚════════════════════════════════════════════════╝
"""


def main():
    print(AYUDA)
    verificar_modelo()

    game = Game()

    while not game.nivel_terminado:
        game.print_board()

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
            print("  ↩  Turno cancelado.")
            continue

        turno_consumido = ejecutar(game, data)

        if game.nivel_terminado:
            break

        # ── Turno de los orcos ────────────────────────────
        if turno_consumido:
            orco_atacante = game.turno_orcos()

            # Si un orco llegó al jugador → combate con prioridad del orco
            if orco_atacante and not game.nivel_terminado:
                print(f"\n  ⚠  ¡Orco {orco_atacante.idx} se abalanzó sobre vos!")
                combate(game, orco_atacante, primer_ataque="orco")

        print()

    # ── Pantalla final ────────────────────────────────────
    if game.nivel_terminado:
        game.print_board()
        if game.victoria:
            print("  ★━━━━━━━━━━━━━━━━━━━━━━━━━━★")
            print("  ★    ¡NIVEL COMPLETADO!     ★")
            print(f"  ★    Oro recogido: {game.jugador.oro}           ★")
            print("  ★━━━━━━━━━━━━━━━━━━━━━━━━━━★\n")
        else:
            print("  ☠━━━━━━━━━━━━━━━━━━━━━━━━━━☠")
            print("  ☠        GAME  OVER         ☠")
            print("  ☠━━━━━━━━━━━━━━━━━━━━━━━━━━☠\n")


if __name__ == "__main__":
    main()