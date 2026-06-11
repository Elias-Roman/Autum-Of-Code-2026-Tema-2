extends Node

# ═══════════════════════════════════════════════════════════
#  GAMESTATE.GD  — Autoload singleton
#  Replica exacta de la lógica de Dungeon.py
# ═══════════════════════════════════════════════════════════

const SIZE = 7
const PLAYER = "K"
const CHEST  = "C"
const OGRE   = "O"
const DOOR   = "D"
const KEY    = "L"
const EMPTY  = "."

# ── Señales ───────────────────────────────────────────────
signal board_changed()
signal message_posted(text: String, color: String)
signal combat_started(orco_idx: int)
signal combat_ended()
signal game_over(victoria: bool)
signal llave_recogida()
signal cofre_abierto(oro: int)
signal llm_thinking(thinking: bool)

# ── Estado jugador ────────────────────────────────────────
var player_r    := 3
var player_c    := 3
var player_hp   := 3.0
var player_oro  := 0
var player_llave := false
var player_defendiendo := false

# ── Orcos [{r,c,hp,idx,vivo}] ────────────────────────────
var orcos: Array = []

# ── Cofres [{r,c,abierto}] ───────────────────────────────
var cofres: Array = []

# ── Puerta / Llave ────────────────────────────────────────
var puerta_r := 0
var puerta_c := 3
var llave_r  := 5
var llave_c  := 1
var llave_recogida_flag := false

# ── Tablero ───────────────────────────────────────────────
var board: Array = []   # board[r][c] = String
var under_player := EMPTY

# ── Flags ─────────────────────────────────────────────────
var nivel_terminado := false
var victoria        := false
var en_combate      := false
var orco_combate_idx := -1   # idx del orco en combate activo

# ── Directions ───────────────────────────────────────────
const DIRS_8 := {
	"arriba":           Vector2i(-1,  0),
	"abajo":            Vector2i( 1,  0),
	"izquierda":        Vector2i( 0, -1),
	"derecha":          Vector2i( 0,  1),
	"arriba-izquierda": Vector2i(-1, -1),
	"arriba-derecha":   Vector2i(-1,  1),
	"abajo-izquierda":  Vector2i( 1, -1),
	"abajo-derecha":    Vector2i( 1,  1),
}
const DIRS_4 := ["arriba", "abajo", "izquierda", "derecha"]


func _ready():
	cargar_nivel()


func cargar_nivel():
	board = []
	for r in SIZE:
		var row = []
		for c in SIZE:
			row.append(EMPTY)
		board.append(row)

	player_r = 3; player_c = 3
	player_hp = 3.0; player_oro = 0
	player_llave = false; player_defendiendo = false

	puerta_r = 0; puerta_c = 3
	llave_r  = 5; llave_c  = 1
	llave_recogida_flag = false

	orcos = [
		{r=2, c=5, hp=2.0, idx=1, vivo=true},
		{r=5, c=5, hp=1.0, idx=2, vivo=true},
	]
	cofres = [
		{r=3, c=1, abierto=false},
	]

	under_player = EMPTY
	nivel_terminado = false
	victoria = false
	en_combate = false
	orco_combate_idx = -1

	board[player_r][player_c] = PLAYER
	board[puerta_r][puerta_c] = DOOR
	board[llave_r][llave_c]   = KEY
	for o in orcos:
		board[o.r][o.c] = OGRE
	for cf in cofres:
		board[cf.r][cf.c] = CHEST

	board_changed.emit()


# ── Helpers ───────────────────────────────────────────────
func dentro(r: int, c: int) -> bool:
	return r >= 0 and r < SIZE and c >= 0 and c < SIZE

func get_cell(r: int, c: int) -> String:
	return board[r][c]

func set_cell(r: int, c: int, sym: String):
	board[r][c] = sym

func orco_en(r: int, c: int):
	for o in orcos:
		if o.vivo and o.r == r and o.c == c:
			return o
	return null

func cofre_en(r: int, c: int):
	for cf in cofres:
		if not cf.abierto and cf.r == r and cf.c == c:
			return cf
	return null

func find_nearest(symbol: String) -> Vector2i:
	var best_dist := 999999
	var best_pos  := Vector2i(-1, -1)
	for r in SIZE:
		for c in SIZE:
			if board[r][c] == symbol:
				var dist = max(abs(player_r - r), abs(player_c - c))
				if dist < best_dist:
					best_dist = dist
					best_pos  = Vector2i(r, c)
	return best_pos


# ═══════════════════════════════════════════════════════════
#  EJECUTAR ACCIÓN DEL JUGADOR
# ═══════════════════════════════════════════════════════════

func ejecutar_accion(data: Dictionary) -> bool:
	"""Devuelve true si el turno fue consumido."""
	if nivel_terminado:
		return false

	var accion = str(data.get("accion", "")).to_lower().strip_edges()

	if accion == "mover":
		return _accion_mover(data)
	elif accion == "abrir":
		return _accion_abrir(data)
	elif accion == "esperar":
		emit_message("· Turno pasado.", "#aaaaaa")
		return true
	elif accion == "desconocido":
		emit_message("✗ No entendí. Ej: 've arriba', 'ir al orco', 'abrir derecha'", "#ff6666")
		return false
	else:
		emit_message("✗ Acción no reconocida: " + accion, "#ff6666")
		return false


func _accion_mover(data: Dictionary) -> bool:
	if "objetivo" in data:
		return _mover_a_objetivo(str(data["objetivo"]).to_lower().strip_edges())
	elif "pasos" in data:
		return _mover_por_pasos(data["pasos"])
	else:
		emit_message("✗ 'mover' sin objetivo ni pasos.", "#ff6666")
		return true


func _mover_a_objetivo(nombre: String) -> bool:
	var OBJETIVO_MAP = {"cofre": CHEST, "orco": OGRE, "puerta": DOOR, "llave": KEY}
	if not nombre in OBJETIVO_MAP:
		emit_message("✗ Objetivo desconocido: '" + nombre + "'", "#ff6666")
		return true

	var simbolo = OBJETIVO_MAP[nombre]
	var target  = find_nearest(simbolo)
	if target == Vector2i(-1, -1):
		emit_message("✗ No hay '" + nombre + "' en el tablero.", "#ff6666")
		return true

	var tr = target.x; var tc = target.y
	emit_message("→ Hacia '" + nombre + "' en (%d,%d)" % [tr, tc], "#aaccff")

	if player_r == tr and player_c == tc:
		emit_message("· Ya estás en '" + nombre + "'.", "#aaaaaa")
		return true

	# Si adyacente a orco → combate
	var dist_cheby = max(abs(player_r - tr), abs(player_c - tc))
	if simbolo == OGRE and dist_cheby <= 1:
		var o = orco_en(tr, tc)
		if o:
			emit_message("⚔ ¡Llegaste al orco! Iniciando combate.", "#ffaa00")
			_iniciar_combate(o, "jugador")
			return true

	_mover_un_paso_hacia(tr, tc)
	return true


func _mover_por_pasos(pasos) -> bool:
	if not pasos is Array or pasos.is_empty():
		emit_message("✗ Campo 'pasos' inválido.", "#ff6666")
		return true

	var paso = pasos[0]
	if not paso is Dictionary:
		emit_message("✗ Paso 1: formato inválido.", "#ff6666")
		return true

	var dir_raw = str(paso.get("direccion", "")).to_lower().strip_edges()
	if not dir_raw in DIRS_8:
		emit_message("✗ Dirección inválida: '" + dir_raw + "'", "#ff6666")
		return true

	if pasos.size() > 1:
		emit_message("ℹ Solo se mueve 1 celda por turno → " + dir_raw, "#aaaaaa")

	var delta = DIRS_8[dir_raw]
	var nr = player_r + delta.x
	var nc = player_c + delta.y

	if not dentro(nr, nc):
		emit_message("✗ Fuera del tablero.", "#ff6666")
		return true

	var sym = get_cell(nr, nc)

	# Contacto con orco → combate
	if sym == OGRE:
		var o = orco_en(nr, nc)
		if o:
			emit_message("⚔ ¡Contacto con orco! Iniciando combate.", "#ffaa00")
			_iniciar_combate(o, "jugador")
			return true

	_aplicar_mover_jugador(dir_raw)
	return true


func _mover_un_paso_hacia(tr: int, tc: int) -> bool:
	if player_r == tr and player_c == tc:
		return false

	var best_score := Vector2i(999, 999)
	var best_dir   := ""

	for dir_str in DIRS_8:
		var delta = DIRS_8[dir_str]
		var nr = player_r + delta.x
		var nc = player_c + delta.y
		if not dentro(nr, nc):
			continue
		var sym = get_cell(nr, nc)
		if sym != EMPTY and sym != DOOR and sym != KEY:
			continue
		var sc = Vector2i(max(abs(nr - tr), abs(nc - tc)), abs(nr - tr) + abs(nc - tc))
		if sc < best_score:
			best_score = sc
			best_dir   = dir_str

	if best_dir == "":
		return false

	_aplicar_mover_jugador(best_dir)
	return true


func _aplicar_mover_jugador(dir_str: String):
	var delta = DIRS_8[dir_str]
	var nr = player_r + delta.x
	var nc = player_c + delta.y

	if not dentro(nr, nc):
		return

	var sym = get_cell(nr, nc)

	# Restaurar celda actual
	set_cell(player_r, player_c, under_player)

	# Recoger llave
	if sym == KEY:
		player_llave = true
		llave_recogida_flag = true
		under_player = EMPTY
		emit_message("🗝 ¡Recogiste la llave!", "#ffdd44")
		llave_recogida.emit()
	else:
		under_player = sym

	player_r = nr
	player_c = nc
	set_cell(nr, nc, PLAYER)

	# Cruzar puerta con llave
	if sym == DOOR and player_llave:
		emit_message("★ ¡Has cruzado la puerta! ¡Nivel completado!", "#44ff88")
		nivel_terminado = true
		victoria = true
		board_changed.emit()
		game_over.emit(true)
		return

	board_changed.emit()


func _accion_abrir(data: Dictionary) -> bool:
	var dir_raw = str(data.get("direccion", "")).to_lower().strip_edges()
	if not dir_raw in DIRS_4:
		emit_message("✗ Solo 4 direcciones cardinales para abrir.", "#ff6666")
		return true

	var delta = DIRS_8[dir_raw]
	var nr = player_r + delta.x
	var nc = player_c + delta.y

	if not dentro(nr, nc):
		emit_message("✗ Fuera del tablero.", "#ff6666")
		return true

	var sym = get_cell(nr, nc)
	if sym != CHEST:
		if sym == OGRE:
			emit_message("✗ Eso es un orco, no un cofre.", "#ff6666")
		elif sym == DOOR:
			emit_message("✗ La puerta se cruza caminando con la llave.", "#ff6666")
		else:
			emit_message("✗ No hay cofre en esa dirección.", "#ff6666")
		return true

	var cf = cofre_en(nr, nc)
	if cf:
		cf.abierto = true
		set_cell(nr, nc, EMPTY)
		player_oro += 1
		emit_message("📦 ¡Cofre abierto! Oro: %d" % player_oro, "#ffdd44")
		cofre_abierto.emit(player_oro)
		board_changed.emit()
	return true


# ═══════════════════════════════════════════════════════════
#  IA DE ORCOS
# ═══════════════════════════════════════════════════════════

func turno_orcos():
	"""Ejecuta el turno de todos los orcos. Devuelve orco atacante o null."""
	var DELTAS_4 = [Vector2i(-1,0), Vector2i(1,0), Vector2i(0,-1), Vector2i(0,1)]
	var DIR_POR_DELTA = {
		Vector2i(-1,0): "arriba", Vector2i(1,0): "abajo",
		Vector2i(0,-1): "izquierda", Vector2i(0,1): "derecha"
	}
	var orco_atacante = null

	for o in orcos:
		if not o.vivo or nivel_terminado:
			continue
		var ya_adj = false
		for d in DELTAS_4:
			if o.r + d.x == player_r and o.c + d.y == player_c:
				ya_adj = true
				break

		if ya_adj:
			if orco_atacante == null:
				orco_atacante = o
			continue

		# Moverse hacia jugador
		var mejor_delta = Vector2i(0, 0)
		var mejor_dist = abs(o.r - player_r) + abs(o.c - player_c)
		var hay_mejor = false
		for d in DELTAS_4:
			var nr = o.r + d.x
			var nc = o.c + d.y
			if not dentro(nr, nc):
				continue
			if get_cell(nr, nc) != EMPTY:
				continue
			var dist = abs(nr - player_r) + abs(nc - player_c)
			if dist < mejor_dist:
				mejor_dist = dist
				mejor_delta = d
				hay_mejor = true

		if hay_mejor:
			set_cell(o.r, o.c, EMPTY)
			o.r += mejor_delta.x
			o.c += mejor_delta.y
			set_cell(o.r, o.c, OGRE)

	board_changed.emit()
	return orco_atacante


# ═══════════════════════════════════════════════════════════
#  COMBATE
# ═══════════════════════════════════════════════════════════

func _iniciar_combate(orco: Dictionary, primer_ataque: String):
	en_combate = true
	orco_combate_idx = orco.idx

	if primer_ataque == "orco":
		# El orco golpea primero
		var dmg = 0.5 if player_defendiendo else 1.0
		player_hp = max(snappedf(player_hp - dmg, 0.1), 0.0)
		emit_message("⚠ ¡Orco %d golpea primero! Daño: %.1f. HP: %.1f" % [orco.idx, dmg, player_hp], "#ff4444")
		if player_hp <= 0:
			nivel_terminado = true
			en_combate = false
			board_changed.emit()
			game_over.emit(false)
			return

	combat_started.emit(orco.idx)


func ejecutar_accion_combate(data: Dictionary):
	"""Procesa una acción dentro del bucle de combate."""
	var orco = _get_orco_by_idx(orco_combate_idx)
	if orco == null:
		return

	var accion = str(data.get("accion", "")).to_lower().strip_edges()

	if accion == "atacar":
		orco.hp = max(snappedf(orco.hp - 1.0, 0.1), 0.0)
		if orco.hp <= 0:
			orco.vivo = false
			set_cell(orco.r, orco.c, EMPTY)
			emit_message("⚔ ¡Orco %d derrotado!" % orco.idx, "#44ff88")
			board_changed.emit()
			en_combate = false
			combat_ended.emit()
			player_defendiendo = false
			return
		else:
			emit_message("⚔ Golpeaste al Orco %d. HP: %.1f" % [orco.idx, orco.hp], "#ffaa00")

	elif accion == "defensa":
		player_defendiendo = true
		emit_message("🛡 En guardia. Daño reducido este turno.", "#44aaff")

	else:
		emit_message("❓ No entendí. Escribí: atacar o defensa.", "#ff6666")
		return

	# Turno del orco (contraataque)
	var dmg = 0.5 if player_defendiendo else 1.0
	player_hp = max(snappedf(player_hp - dmg, 0.1), 0.0)
	emit_message("⚔ Orco %d contraatacó. Daño: %.1f. HP: %.1f/3.0" % [orco.idx, dmg, player_hp], "#ff4444")
	player_defendiendo = false

	board_changed.emit()

	if player_hp <= 0:
		nivel_terminado = true
		en_combate = false
		game_over.emit(false)
	else:
		# Refrescar UI de combate
		combat_started.emit(orco.idx)


func _get_orco_by_idx(idx: int):
	for o in orcos:
		if o.idx == idx:
			return o
	return null


# ═══════════════════════════════════════════════════════════
#  POST-TURNO
# ═══════════════════════════════════════════════════════════

func post_turno_jugador():
	"""Llama al turno de orcos después de que el jugador actúa (fuera de combate)."""
	if nivel_terminado or en_combate:
		return
	var atacante = turno_orcos()
	if atacante and not nivel_terminado:
		emit_message("⚠ ¡Orco %d se abalanza sobre vos!" % atacante.idx, "#ffaa00")
		_iniciar_combate(atacante, "orco")


# ── Utilidad ─────────────────────────────────────────────
func emit_message(text: String, color: String = "#ffffff"):
	message_posted.emit(text, color)
