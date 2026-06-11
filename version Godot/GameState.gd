extends Node

# ═══════════════════════════════════════════════════════════
#  GAMESTATE.GD  v5
#  Tres capas:
#   board_bg[r][c]  = piso ("." siempre)
#   board_obj[r][c] = objetos fijos (D, C, C_OPEN, D_OPEN, L)
#   board_fg[r][c]  = personajes móviles (K, K_DEAD, O)
#
#  Reglas de colisión:
#   - K no puede entrar en celda con O ni con C / C_OPEN
#   - K puede entrar en D (con llave → abre y termina)
#   - K puede entrar en L (la recoge)
#   - O no puede entrar en celda con C, L, D ni con K
# ═══════════════════════════════════════════════════════════

const SIZE   = 7
const PLAYER = "K"
const CHEST  = "C"
const OGRE   = "O"
const DOOR   = "D"
const KEY    = "L"
const EMPTY  = "."

const PLAYER_DEAD = "K_DEAD"
const CHEST_OPEN  = "C_OPEN"
const DOOR_OPEN   = "D_OPEN"

signal board_changed()
signal message_posted(text: String, color: String)
signal combat_started(orco_idx: int)
signal combat_ended()
signal game_over(victoria: bool)
signal llave_recogida()
signal cofre_abierto(oro: int)
signal llm_thinking(thinking: bool)

var player_r           := 3
var player_c           := 3
var player_hp          := 3.0
var player_oro         := 0
var player_llave       := false
var player_defendiendo := false

var orcos:  Array = []
var cofres: Array = []

var puerta_r       := 0
var puerta_c       := 3
var puerta_abierta := false
var llave_r        := 5
var llave_c        := 1

# ── Capas ─────────────────────────────────────────────────
var board_obj: Array = []  # objetos fijos (D, C, L, variantes)
var board_fg:  Array = []  # personajes móviles (K, O, K_DEAD)
# alias para compatibilidad externa (Main.gd accede a board_fg)
var board: Array = []

# ── Flags ─────────────────────────────────────────────────
var nivel_terminado  := false
var victoria         := false
var en_combate       := false
var orco_combate_idx := -1

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


func notify_thinking(val: bool):
	llm_thinking.emit(val)


func cargar_nivel():
	board_obj = []
	board_fg  = []
	for r in SIZE:
		var obj_row = []; var fg_row = []
		for c in SIZE:
			obj_row.append("")
			fg_row.append("")
		board_obj.append(obj_row)
		board_fg.append(fg_row)
	board = board_fg

	player_r = 3; player_c = 3
	player_hp = 3.0; player_oro = 0
	player_llave = false; player_defendiendo = false

	puerta_r = 0; puerta_c = 3; puerta_abierta = false
	llave_r  = 5; llave_c  = 1

	orcos = [
		{r=2, c=5, hp=2.0, idx=1, vivo=true},
		{r=5, c=5, hp=1.0, idx=2, vivo=true},
	]
	cofres = [{r=3, c=1, abierto=false}]

	nivel_terminado = false; victoria = false
	en_combate = false; orco_combate_idx = -1

	# Poblar capas
	board_obj[puerta_r][puerta_c] = DOOR
	board_obj[llave_r][llave_c]   = KEY
	for cf in cofres:
		board_obj[cf.r][cf.c] = CHEST
	board_fg[player_r][player_c] = PLAYER
	for o in orcos:
		board_fg[o.r][o.c] = OGRE

	board_changed.emit()


# ── Helpers ───────────────────────────────────────────────

func dentro(r: int, c: int) -> bool:
	return r >= 0 and r < SIZE and c >= 0 and c < SIZE

func obj_en(r: int, c: int) -> String:
	return board_obj[r][c]

func fg_en(r: int, c: int) -> String:
	return board_fg[r][c]

# celda "ocupada" para el jugador: hay personaje enemigo O cofre
func bloqueado_para_jugador(r: int, c: int) -> String:
	var fg  = board_fg[r][c]
	var obj = board_obj[r][c]
	if fg == OGRE:             return OGRE
	if obj == CHEST or obj == CHEST_OPEN: return CHEST
	return ""

# celda bloqueada para orcos
func bloqueado_para_orco(r: int, c: int) -> bool:
	if board_fg[r][c] != "":  return true   # otro personaje
	var obj = board_obj[r][c]
	return obj == CHEST or obj == CHEST_OPEN or obj == DOOR or obj == KEY

func orco_en(r: int, c: int):
	for o in orcos:
		if o.vivo and o.r == r and o.c == c: return o
	return null

func cofre_en(r: int, c: int):
	for cf in cofres:
		if not cf.abierto and cf.r == r and cf.c == c: return cf
	return null

func find_nearest_obj(symbol: String) -> Vector2i:
	var best_dist := 999999; var best_pos := Vector2i(-1,-1)
	for r in SIZE:
		for c in SIZE:
			if board_obj[r][c] == symbol:
				var d = max(abs(player_r-r), abs(player_c-c))
				if d < best_dist: best_dist = d; best_pos = Vector2i(r,c)
	return best_pos

func find_nearest_fg(symbol: String) -> Vector2i:
	var best_dist := 999999; var best_pos := Vector2i(-1,-1)
	for r in SIZE:
		for c in SIZE:
			if board_fg[r][c] == symbol:
				var d = max(abs(player_r-r), abs(player_c-c))
				if d < best_dist: best_dist = d; best_pos = Vector2i(r,c)
	return best_pos


# ═══════════════════════════════════════════════════════════
#  ACCIONES JUGADOR
# ═══════════════════════════════════════════════════════════

func ejecutar_accion(data: Dictionary) -> bool:
	if nivel_terminado: return false
	var accion = str(data.get("accion","")).to_lower().strip_edges()
	if   accion == "mover":      return _accion_mover(data)
	elif accion == "abrir":      return _accion_abrir(data)
	elif accion == "esperar":    emit_message("· Turno pasado.", "#aaaaaa"); return true
	elif accion == "desconocido":
		emit_message("✗ No entendí. Ej: 've arriba', 'ir al orco', 'abrir izquierda'", "#ff6666")
		return false
	else:
		emit_message("✗ Acción: " + accion, "#ff6666"); return false


func _accion_mover(data: Dictionary) -> bool:
	if   "objetivo" in data: return _mover_a_objetivo(str(data["objetivo"]).to_lower().strip_edges())
	elif "pasos"    in data: return _mover_por_pasos(data["pasos"])
	emit_message("✗ 'mover' sin destino.", "#ff6666"); return true


func _mover_a_objetivo(nombre: String) -> bool:
	var MAPA_SYM := {"orco": OGRE, "puerta": DOOR, "llave": KEY, "cofre": CHEST}
	if not nombre in MAPA_SYM:
		emit_message("✗ Objetivo desconocido: '" + nombre + "'", "#ff6666"); return true

	var simbolo = MAPA_SYM[nombre]
	var target  : Vector2i
	if simbolo == OGRE: target = find_nearest_fg(OGRE)
	else:               target = find_nearest_obj(simbolo)

	if target == Vector2i(-1,-1):
		emit_message("✗ No hay '" + nombre + "' en el tablero.", "#ff6666"); return true

	var dest_r = target.x; var dest_c = target.y
	emit_message("→ Hacia '" + nombre + "' en (%d,%d)" % [dest_r, dest_c], "#aaccff")

	if player_r == dest_r and player_c == dest_c:
		emit_message("· Ya estás ahí.", "#aaaaaa"); return true

	# Adyacente a orco → combate
	if simbolo == OGRE and max(abs(player_r-dest_r), abs(player_c-dest_c)) <= 1:
		var o = orco_en(dest_r, dest_c)
		if o: _iniciar_combate(o, "jugador"); return true

	_mover_un_paso_hacia(dest_r, dest_c)
	return true


func _mover_por_pasos(pasos) -> bool:
	if not pasos is Array or pasos.is_empty():
		emit_message("✗ Pasos inválidos.", "#ff6666"); return true
	var paso = pasos[0]
	if not paso is Dictionary:
		emit_message("✗ Formato de paso inválido.", "#ff6666"); return true
	var dir_raw = str(paso.get("direccion","")).to_lower().strip_edges()
	if not dir_raw in DIRS_8:
		emit_message("✗ Dirección inválida: '" + dir_raw + "'", "#ff6666"); return true

	var delta = DIRS_8[dir_raw]
	var nr = player_r + delta.x
	var nc = player_c + delta.y

	if not dentro(nr, nc):
		emit_message("✗ Límite del tablero.", "#ff6666"); return true

	# Verificar colisión
	var bloq = bloqueado_para_jugador(nr, nc)
	if bloq == OGRE:
		var o = orco_en(nr, nc)
		if o: emit_message("⚔ ¡Contacto con orco!", "#ffaa00"); _iniciar_combate(o, "jugador"); return true
	if bloq == CHEST:
		emit_message("✗ Casilla ocupada por Cofre. Usá 'abrir' para interactuar.", "#ffaa66"); return true

	_aplicar_mover_jugador(dir_raw)
	return true


func _mover_un_paso_hacia(dest_r: int, dest_c: int) -> bool:
	if player_r == dest_r and player_c == dest_c: return false
	var best_score := Vector2i(999,999); var best_dir := ""
	for dir_str in DIRS_8:
		var delta = DIRS_8[dir_str]
		var nr = player_r + delta.x; var nc = player_c + delta.y
		if not dentro(nr, nc): continue
		# Bloqueado por cofre o enemigo (no por puerta ni llave)
		var bloq = bloqueado_para_jugador(nr, nc)
		if bloq == CHEST: continue
		if bloq == OGRE and not (nr == dest_r and nc == dest_c): continue
		var sc = Vector2i(max(abs(nr-dest_r), abs(nc-dest_c)), abs(nr-dest_r)+abs(nc-dest_c))
		if sc < best_score: best_score = sc; best_dir = dir_str
	if best_dir == "": return false
	_aplicar_mover_jugador(best_dir)
	return true


func _aplicar_mover_jugador(dir_str: String):
	var delta = DIRS_8[dir_str]
	var nr = player_r + delta.x
	var nc = player_c + delta.y
	if not dentro(nr, nc): return

	var obj = board_obj[nr][nc]

	# Retirar jugador de celda actual
	board_fg[player_r][player_c] = ""

	# Interacción con objeto en destino
	if obj == KEY:
		player_llave = true
		board_obj[nr][nc] = ""   # llave desaparece del mapa al recogerla
		emit_message("🗝 ¡Recogiste la llave!", "#ffdd44")
		llave_recogida.emit()

	elif obj == DOOR:
		if player_llave:
			board_obj[nr][nc] = DOOR_OPEN
			emit_message("★ ¡Abriste la puerta! ¡Nivel completado!", "#44ff88")
			player_r = nr; player_c = nc
			board_fg[nr][nc] = PLAYER
			nivel_terminado = true; victoria = true
			board_changed.emit()
			game_over.emit(true)
			return
		else:
			emit_message("🔒 La puerta está cerrada. Necesitás la llave primero.", "#ffaa44")
			# Jugador NO entra: volver a la celda original
			board_fg[player_r][player_c] = PLAYER
			board_changed.emit()
			return

	# Mover jugador
	player_r = nr; player_c = nc
	board_fg[nr][nc] = PLAYER
	board_changed.emit()


func _accion_abrir(data: Dictionary) -> bool:
	var dir_raw = str(data.get("direccion","")).to_lower().strip_edges()
	if not dir_raw in DIRS_4:
		emit_message("✗ Dirección inválida para abrir.", "#ff6666"); return true
	var delta = DIRS_8[dir_raw]
	var nr = player_r + delta.x; var nc = player_c + delta.y
	if not dentro(nr, nc):
		emit_message("✗ Fuera del tablero.", "#ff6666"); return true

	var obj = board_obj[nr][nc]
	var fg  = board_fg[nr][nc]

	if obj == CHEST:
		var cf = cofre_en(nr, nc)
		if cf:
			cf.abierto = true
			board_obj[nr][nc] = CHEST_OPEN
			player_oro += 1
			emit_message("📦 ¡Cofre abierto! Oro: %d" % player_oro, "#ffdd44")
			cofre_abierto.emit(player_oro)
			board_changed.emit()
	elif obj == CHEST_OPEN:
		emit_message("· El cofre ya está abierto.", "#aaaaaa")
	elif obj == DOOR:
		if player_llave:
			emit_message("→ Caminá hacia la puerta para cruzarla.", "#aaccff")
		else:
			emit_message("🔒 La puerta está cerrada. Necesitás la llave.", "#ffaa44")
	elif fg == OGRE:
		emit_message("✗ Eso es un orco. Usá 'atacar' en combate.", "#ff6666")
	else:
		var bloq_name := ""
		if obj != "": bloq_name = obj
		elif fg != "": bloq_name = fg
		if bloq_name != "":
			emit_message("✗ Casilla ocupada por: " + bloq_name, "#ff6666")
		else:
			emit_message("✗ No hay nada que abrir en esa dirección.", "#ff6666")
	return true


# ═══════════════════════════════════════════════════════════
#  IA DE ORCOS
# ═══════════════════════════════════════════════════════════

func turno_orcos():
	var DELTAS_4 = [Vector2i(-1,0), Vector2i(1,0), Vector2i(0,-1), Vector2i(0,1)]
	var orco_atacante = null
	for o in orcos:
		if not o.vivo or nivel_terminado: continue
		var ya_adj = false
		for d in DELTAS_4:
			if o.r+d.x == player_r and o.c+d.y == player_c:
				ya_adj = true; break
		if ya_adj:
			if orco_atacante == null: orco_atacante = o
			continue
		var mejor_delta := Vector2i(0,0)
		var mejor_dist  : int = abs(o.r-player_r) + abs(o.c-player_c)
		var hay_mejor   := false
		for d in DELTAS_4:
			var nr = o.r+d.x; var nc = o.c+d.y
			if not dentro(nr, nc): continue
			if bloqueado_para_orco(nr, nc): continue
			var dist = abs(nr-player_r) + abs(nc-player_c)
			if dist < mejor_dist:
				mejor_dist = dist; mejor_delta = d; hay_mejor = true
		if hay_mejor:
			board_fg[o.r][o.c] = ""
			o.r += mejor_delta.x; o.c += mejor_delta.y
			board_fg[o.r][o.c] = OGRE
	board_changed.emit()
	return orco_atacante


# ═══════════════════════════════════════════════════════════
#  COMBATE
# ═══════════════════════════════════════════════════════════

func _iniciar_combate(orco: Dictionary, primer_ataque: String):
	en_combate = true; orco_combate_idx = orco.idx
	if primer_ataque == "orco":
		var dmg = 0.5 if player_defendiendo else 1.0
		player_hp = max(snappedf(player_hp-dmg, 0.1), 0.0)
		emit_message("⚠ ¡Orco %d golpea primero! Daño: %.1f. HP: %.1f" % [orco.idx, dmg, player_hp], "#ff4444")
		if player_hp <= 0:
			nivel_terminado = true; en_combate = false
			board_fg[player_r][player_c] = PLAYER_DEAD
			board_changed.emit(); game_over.emit(false); return
	combat_started.emit(orco.idx)


func ejecutar_accion_combate(data: Dictionary):
	var orco = _get_orco_by_idx(orco_combate_idx)
	if orco == null: return
	var accion = str(data.get("accion","")).to_lower().strip_edges()

	if accion == "atacar":
		orco.hp = max(snappedf(orco.hp-1.0, 0.1), 0.0)
		if orco.hp <= 0:
			orco.vivo = false
			board_fg[orco.r][orco.c] = ""
			emit_message("⚔ ¡Orco %d derrotado!" % orco.idx, "#44ff88")
			board_changed.emit(); en_combate = false
			combat_ended.emit(); player_defendiendo = false; return
		else:
			emit_message("⚔ Golpeaste al Orco %d. HP: %.1f" % [orco.idx, orco.hp], "#ffaa00")
	elif accion == "defensa":
		player_defendiendo = true
		emit_message("🛡 En guardia. Daño reducido este turno.", "#44aaff")
	else:
		emit_message("❓ Elegí: Golpear  o  Guardia", "#ff6666"); return

	var dmg = 0.5 if player_defendiendo else 1.0
	player_hp = max(snappedf(player_hp-dmg, 0.1), 0.0)
	emit_message("⚔ Orco %d contraatacó. Daño: %.1f. HP: %.1f/3.0" % [orco.idx, dmg, player_hp], "#ff4444")
	player_defendiendo = false
	board_changed.emit()

	if player_hp <= 0:
		nivel_terminado = true; en_combate = false
		board_fg[player_r][player_c] = PLAYER_DEAD
		board_changed.emit(); game_over.emit(false)
	else:
		combat_started.emit(orco.idx)


func _get_orco_by_idx(idx: int):
	for o in orcos:
		if o.idx == idx: return o
	return null


func post_turno_jugador():
	if nivel_terminado or en_combate: return
	var atacante = turno_orcos()
	if atacante and not nivel_terminado:
		emit_message("⚠ ¡Orco %d se abalanza sobre vos!" % atacante.idx, "#ffaa00")
		_iniciar_combate(atacante, "orco")


func emit_message(text: String, color: String = "#ffffff"):
	message_posted.emit(text, color)
